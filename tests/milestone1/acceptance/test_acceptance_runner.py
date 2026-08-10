from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from scripts.milestone1_acceptance import build_gates, execute


class _TemporaryDirectory:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> str:
        self.path.mkdir()
        return str(self.path)

    def __exit__(self, *_args: object) -> None:
        shutil.rmtree(self.path)


def test_gate_definitions_are_bounded_data_without_recursive_acceptance_calls() -> None:
    focused = build_gates("focused")
    full = build_gates("full")

    assert [gate.name for gate in focused] == [
        "contract-check",
        "milestone1-tests",
        "legacy-regressions",
        "workbench-boundaries",
        "phase8-offline-acceptance",
        "phase9-offline-acceptance",
    ]
    assert [gate.name for gate in full[: len(focused)]] == [gate.name for gate in focused]
    assert [gate.name for gate in full[len(focused) :]] == [
        "ruff-full",
        "pytest-full",
        "web-lint",
        "web-typecheck",
        "web-build-default",
        "web-build-enabled",
    ]
    for gate in full:
        assert "milestone1_acceptance.py" not in gate.argv
        assert gate.argv


def test_execute_sanitizes_subprocess_environment_and_cleans_temporary_directory(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret")
    monkeypatch.setenv("MANIM_WORKBENCH_INTERNAL_TOKEN", "internal-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "cloud-secret")
    temp_dir = tmp_path / "acceptance-private"
    calls: list[dict[str, object]] = []

    def runner(argv, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"argv": argv, **kwargs})
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="provider output with sk-test-secret\n",
            stderr="private path /tmp/should-not-print\n",
        )

    result = execute(
        "focused",
        runner=runner,
        temp_factory=lambda **_kwargs: _TemporaryDirectory(temp_dir),
    )

    assert result == 0
    assert not temp_dir.exists()
    assert len(calls) == len(build_gates("focused"))
    for call in calls:
        environment = call["env"]
        assert isinstance(environment, dict)
        assert "DEEPSEEK_API_KEY" not in environment
        assert "MANIM_WORKBENCH_INTERNAL_TOKEN" not in environment
        assert "AWS_SECRET_ACCESS_KEY" not in environment
        assert environment["NEXT_PUBLIC_EXPERIMENT_LAB_ENABLED"] == "false"
        assert environment["NEXT_PUBLIC_STUDIO_ENABLED"] == "false"
        database_url = str(environment["MANIM_WORKBENCH_DATABASE_URL"])
        assert database_url.startswith("sqlite:///")
        assert str(temp_dir) in database_url

    output = capsys.readouterr().out
    assert "sk-test-secret" not in output
    assert "/tmp/should-not-print" not in output
    summary = json.loads(output)
    assert summary["status"] == "passed"
    assert summary["gate_count"] == len(calls)


def test_execute_fails_fast_and_redacts_captured_failure_output(tmp_path: Path, capsys) -> None:
    temp_dir = tmp_path / "acceptance-private"
    calls: list[tuple[str, ...]] = []

    def runner(argv, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(
            argv,
            17,
            stdout="sensitive prompt sk-failure-secret\n",
            stderr="/home/private/secret.env\n",
        )

    result = execute(
        "focused",
        runner=runner,
        temp_factory=lambda **_kwargs: _TemporaryDirectory(temp_dir),
    )

    assert result == 1
    assert len(calls) == 1
    assert not temp_dir.exists()
    output = capsys.readouterr().out
    assert "sk-failure-secret" not in output
    assert "/home/private/secret.env" not in output
    summary = json.loads(output)
    assert summary == {
        "completed_gates": 0,
        "exit_code": 17,
        "failed_gate": "contract-check",
        "hint": "rerun the named gate locally for detailed diagnostics",
        "mode": "focused",
        "schema_version": "1.0",
        "status": "failed",
    }


def test_full_build_gates_set_feature_flags_independently() -> None:
    gates = {gate.name: gate for gate in build_gates("full")}

    assert gates["web-build-default"].env == {
        "NEXT_PUBLIC_EXPERIMENT_LAB_ENABLED": "false",
        "NEXT_PUBLIC_STUDIO_ENABLED": "false",
    }
    assert gates["web-build-enabled"].env == {
        "NEXT_PUBLIC_EXPERIMENT_LAB_ENABLED": "true",
        "NEXT_PUBLIC_STUDIO_ENABLED": "true",
    }
