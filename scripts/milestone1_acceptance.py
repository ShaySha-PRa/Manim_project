from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]
Mode = Literal["focused", "full"]


@dataclass(frozen=True)
class Gate:
    name: str
    argv: tuple[str, ...]
    env: dict[str, str] = field(default_factory=dict)


def _python(*arguments: str) -> tuple[str, ...]:
    return (sys.executable, *arguments)


def _isolated_pytest(*arguments: str) -> tuple[str, ...]:
    return (sys.executable, "-m", "pytest", *arguments)


def _isolated_script(script: str, *arguments: str) -> tuple[str, ...]:
    return (sys.executable, script, *arguments)


def build_gates(mode: Mode) -> tuple[Gate, ...]:
    focused = (
        Gate("contract-check", _python("scripts/generate_contracts.py", "--check")),
        Gate("milestone1-tests", _isolated_pytest("-s", "-q", "tests/milestone1")),
        Gate(
            "legacy-regressions",
            _isolated_pytest(
                "-s",
                "-q",
                "tests/phase8/auth",
                "tests/phase8/projects",
                "tests/phase8/parent/test_workspace_boundary.py",
                "tests/phase8/delivery",
                "tests/phase5/api",
                "tests/phase5/integration",
                "tests/phase5/runner",
                "tests/phase5/security",
                "tests/phase5/sandbox",
                "tests/phase6/evaluation",
                "tests/phase6/integration",
                "tests/phase6/prompts",
                "tests/phase6/provider",
                "tests/phase6/validation",
                "tests/phase7/blackbox",
                "tests/phase7/integration",
                "tests/phase7/parent",
                "tests/phase7/prompts",
                "tests/phase7/repair",
                "tests/phase7/security",
                "tests/phase7/validation",
                "tests/phase9",
            ),
        ),
        Gate(
            "workbench-boundaries",
            _isolated_pytest("-s", "-q", "tests/web/workbench"),
        ),
        Gate("phase8-offline-acceptance", _isolated_script("scripts/phase8_acceptance.py")),
        Gate("phase9-offline-acceptance", _isolated_script("scripts/phase9_acceptance.py")),
    )
    if mode == "focused":
        return focused
    if mode != "full":
        raise ValueError(f"unsupported acceptance mode: {mode}")
    return focused + (
        Gate("ruff-full", _python("-m", "ruff", "check", ".")),
        Gate("pytest-full", _isolated_pytest("-s", "-q")),
        Gate("web-lint", ("npm", "run", "lint")),
        Gate("web-typecheck", ("npm", "run", "typecheck")),
        Gate(
            "web-build-default",
            ("npm", "run", "build"),
            {
                "NEXT_PUBLIC_EXPERIMENT_LAB_ENABLED": "false",
                "NEXT_PUBLIC_STUDIO_ENABLED": "false",
            },
        ),
        Gate(
            "web-build-enabled",
            ("npm", "run", "build"),
            {
                "NEXT_PUBLIC_EXPERIMENT_LAB_ENABLED": "true",
                "NEXT_PUBLIC_STUDIO_ENABLED": "true",
            },
        ),
    )


def _sanitized_environment(temp_dir: Path) -> dict[str, str]:
    environment = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL", "TZ", "SystemRoot", "WINDIR")
        if key in os.environ
    }
    environment.update(
        {
            "TMPDIR": str(temp_dir),
            "TEMP": str(temp_dir),
            "TMP": str(temp_dir),
            "PYTHONUTF8": "1",
            "PYTHONUNBUFFERED": "1",
            "CI": "1",
            "PYTEST_ADDOPTS": "-p tests.milestone1.acceptance.safe_database",
            "MANIM_WORKBENCH_ACCEPTANCE_ROOT": str(temp_dir),
            "MANIM_WORKBENCH_DATABASE_URL": f"sqlite:///{temp_dir / 'database' / 'acceptance.db'}",
            "MANIM_WORKBENCH_REDIS_URL": "redis://127.0.0.1:6379/0",
            "MANIM_WORKBENCH_API_URL": "http://127.0.0.1:8000",
            "MANIM_WORKBENCH_RUNNER_ID": "runner-acceptance",
            "MANIM_WORKBENCH_RUNNER_ROOT": str(temp_dir / "runtime"),
            "MANIM_WORKBENCH_ARTIFACT_ROOT": str(temp_dir / "runtime" / "artifacts"),
            "MANIM_WORKBENCH_ALLOWED_ORIGINS": "http://localhost:3000",
            "MANIM_WORKBENCH_COOKIE_SECURE": "false",
            "MANIM_WORKBENCH_SESSION_MAX_AGE_SECONDS": "28800",
            "NEXT_PUBLIC_API_URL": "http://127.0.0.1:8000",
            "NEXT_ALLOWED_DEV_ORIGINS": "localhost,127.0.0.1",
            "NEXT_PUBLIC_EXPERIMENT_LAB_ENABLED": "false",
            "NEXT_PUBLIC_STUDIO_ENABLED": "false",
        }
    )
    (temp_dir / "database").mkdir()
    return environment


def execute(
    mode: Mode,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    temp_factory: Callable[..., tempfile.TemporaryDirectory[str]] = tempfile.TemporaryDirectory,
) -> int:
    run = subprocess.run if runner is None else runner
    gates = build_gates(mode)
    with temp_factory(prefix="manim-workbench-m1-") as directory:
        environment = _sanitized_environment(Path(directory))
        for completed_count, gate in enumerate(gates):
            gate_environment = {**environment, **gate.env}
            completed = run(
                gate.argv,
                cwd=ROOT,
                env=gate_environment,
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode:
                print(
                    json.dumps(
                        {
                            "completed_gates": completed_count,
                            "exit_code": completed.returncode,
                            "failed_gate": gate.name,
                            "hint": "rerun the named gate locally for detailed diagnostics",
                            "mode": mode,
                            "schema_version": "1.0",
                            "status": "failed",
                        },
                        sort_keys=True,
                    )
                )
                return 1
    print(
        json.dumps(
            {
                "gate_count": len(gates),
                "mode": mode,
                "schema_version": "1.0",
                "status": "passed",
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded offline Milestone 1 acceptance.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--focused", action="store_true", help="run focused compatibility gates")
    group.add_argument("--full", action="store_true", help="run all offline compatibility gates")
    arguments = parser.parse_args()
    mode: Mode = "full" if arguments.full else "focused"
    return execute(mode)


if __name__ == "__main__":
    raise SystemExit(main())
