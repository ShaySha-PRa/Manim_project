#!/usr/bin/env python3
"""Opt-in, resumable Docker security probes for the Phase 5 sandbox boundary.

The harness is deliberately independent from the runner implementation.  It
uses the immutable renderer image and a stricter, small resource envelope to
prove that Docker's isolation controls work on the host.  Product-specific
command construction and output publishing remain covered by security tests.

Live execution is disabled unless *both* ``PHASE5_RUN_LIVE_ATTACKS=1`` and
``--execute`` are supplied.  Each case has a 15-second-or-less host timeout
and all paths run Docker cleanup in ``finally``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

RECORD_TYPE = "phase5-sandbox-attack-v1"
LIVE_ENVIRONMENT_VARIABLE = "PHASE5_RUN_LIVE_ATTACKS"
DOCKER_IMAGE = "manimcommunity/manim@sha256:f18f53f2e4eaf2ea41713437d34363fb3f5cc6008b03fd798676ac0359396c3b"
MAX_OUTPUT_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class AttackCase:
    """A deliberately hostile input with bounded host-side resource costs."""

    name: str
    source: str
    expected_outcome: str
    timeout_seconds: int
    cpus: float = 0.25
    memory_bytes: int = 128 * 1024 * 1024
    pids_limit: int = 16
    tmpfs_bytes: int = 32 * 1024 * 1024


ATTACK_CASES: tuple[AttackCase, ...] = (
    AttackCase("loop", "while True: pass\n", "sandbox_timeout", 5),
    AttackCase(
        "fork",
        "import os\nwhile True: os.fork()\n",
        "sandbox_pid_limit",
        8,
    ),
    AttackCase(
        "oom",
        "items = []\nwhile True: items.append(b'x' * 8_388_608)\n",
        "sandbox_oom",
        8,
    ),
    AttackCase(
        "disk",
        "from pathlib import Path\nblock=b'x'*1_048_576\nwith Path('/tmp/fill').open('wb') as h:\n"
        "    while True: h.write(block); h.flush()\n",
        "sandbox_output_limit",
        8,
    ),
    AttackCase(
        "network",
        "import socket\ntry:\n    socket.create_connection(('1.1.1.1', 53), 1)\n"
        "except OSError:\n    print('network-blocked')\nelse:\n    raise SystemExit('network-open')\n",
        "sandbox_security_violation",
        5,
    ),
    AttackCase(
        "path",
        "from pathlib import Path\nassert not Path('/host-secret').exists()\nprint('path-blocked')\n",
        "sandbox_security_violation",
        5,
    ),
    AttackCase(
        "symlink",
        "from pathlib import Path\nPath('/output/link').symlink_to('/etc/passwd')\nprint('symlink-created')\n",
        "artifact_publish_failed",
        5,
    ),
    AttackCase(
        "environment",
        "import os\nblocked=('MANIM_WORKBENCH_INTERNAL_TOKEN','OPENAI_API_KEY','HOME_SECRET')\n"
        "assert not any(os.environ.get(k) for k in blocked)\nprint('environment-blocked')\n",
        "sandbox_security_violation",
        5,
    ),
    AttackCase("residual_container", "import time\ntime.sleep(300)\n", "sandbox_timeout", 5),
)

_CASE_BY_NAME = {case.name: case for case in ATTACK_CASES}


@dataclass(frozen=True, slots=True)
class AttackRecord:
    """Validated, non-secret evidence emitted by one actual harness attempt."""

    attack: str
    passed: bool
    expected_outcome: str
    observed_outcome: str
    duration_seconds: float
    recorded_at: str
    command_sha256: str
    returncode: int | None
    timed_out: bool
    container_removed: bool
    output_safe: bool
    record_type: str = RECORD_TYPE

    @classmethod
    def success(cls, attack: str, duration_seconds: float, observed_outcome: str) -> AttackRecord:
        case = _case(attack)
        return cls(
            attack=attack,
            passed=observed_outcome == case.expected_outcome,
            expected_outcome=case.expected_outcome,
            observed_outcome=observed_outcome,
            duration_seconds=duration_seconds,
            recorded_at=_utc_now(),
            command_sha256="0" * 64,
            returncode=0,
            timed_out=False,
            container_removed=True,
            output_safe=True,
        )

    @classmethod
    def failure(cls, attack: str, duration_seconds: float, observed_outcome: str) -> AttackRecord:
        case = _case(attack)
        return cls(
            attack=attack,
            passed=False,
            expected_outcome=case.expected_outcome,
            observed_outcome=observed_outcome,
            duration_seconds=duration_seconds,
            recorded_at=_utc_now(),
            command_sha256="0" * 64,
            returncode=None,
            timed_out=False,
            container_removed=True,
            output_safe=False,
        )

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def live_execution_enabled() -> bool:
    """Require an explicit opt-in; any other value fails closed."""

    return os.environ.get(LIVE_ENVIRONMENT_VARIABLE) == "1"


def append_record(path: Path, record: AttackRecord) -> None:
    """Append one fully encoded record and force it to stable storage."""

    validated = validate_record(record.as_dict())
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(validated, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_number}") from exc
            if not isinstance(raw, dict):
                raise ValueError(f"non-object record at {path}:{line_number}")
            records.append(validate_record(raw))
    return records


def validate_record(record: dict[str, Any]) -> dict[str, Any]:
    required = {
        "record_type",
        "attack",
        "passed",
        "expected_outcome",
        "observed_outcome",
        "duration_seconds",
        "recorded_at",
        "command_sha256",
        "returncode",
        "timed_out",
        "container_removed",
        "output_safe",
    }
    if set(record) != required:
        raise ValueError("attack record is missing record_type or another closed-schema field")
    if record["record_type"] != RECORD_TYPE:
        raise ValueError("attack record has an invalid record_type")
    attack = record["attack"]
    if not isinstance(attack, str) or attack not in _CASE_BY_NAME:
        raise ValueError("attack record names an unknown attack")
    if record["expected_outcome"] != _CASE_BY_NAME[attack].expected_outcome:
        raise ValueError("attack record expected_outcome does not match the case")
    if not isinstance(record["passed"], bool):
        raise ValueError("attack record passed must be a boolean")
    if not isinstance(record["observed_outcome"], str) or not record["observed_outcome"]:
        raise ValueError("attack record needs an observed outcome")
    if not isinstance(record["duration_seconds"], int | float) or record["duration_seconds"] < 0:
        raise ValueError("attack record duration_seconds is invalid")
    if not isinstance(record["recorded_at"], str):
        raise ValueError("attack record recorded_at is invalid")
    command_sha256 = record["command_sha256"]
    if not isinstance(command_sha256, str) or len(command_sha256) != 64:
        raise ValueError("attack record command_sha256 is invalid")
    if not all(character in "0123456789abcdef" for character in command_sha256):
        raise ValueError("attack record command_sha256 is invalid")
    if record["returncode"] is not None and not isinstance(record["returncode"], int):
        raise ValueError("attack record returncode is invalid")
    for name in ("timed_out", "container_removed", "output_safe"):
        if not isinstance(record[name], bool):
            raise ValueError(f"attack record {name} must be a boolean")
    return record


def latest_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        validated = validate_record(record)
        latest[str(validated["attack"])] = validated
    return latest


def completed_attacks(path: Path) -> set[str]:
    return {
        name
        for name, record in latest_records(read_records(path)).items()
        if record["passed"] is True
    }


def summarize(records: list[dict[str, Any]]) -> dict[str, object]:
    latest = latest_records(records)
    missing = sorted(set(_CASE_BY_NAME) - set(latest))
    if missing:
        raise ValueError(f"missing effective evidence for: {', '.join(missing)}")
    failed = sorted(name for name, record in latest.items() if record["passed"] is not True)
    unsafe_cleanup = sorted(
        name
        for name, record in latest.items()
        if record["container_removed"] is not True or record["output_safe"] is not True
    )
    gate_failures = [f"attack failed: {name}" for name in failed]
    gate_failures.extend(f"cleanup or output validation failed: {name}" for name in unsafe_cleanup)
    return {
        "record_count": len(records),
        "effective_record_count": len(latest),
        "expected_attack_count": len(ATTACK_CASES),
        "passed_attack_count": len(latest) - len(failed),
        "failed_attacks": failed,
        "unsafe_cleanup_attacks": unsafe_cleanup,
        "gate_failures": gate_failures,
        "gate_passed": not gate_failures,
    }


def build_docker_command(case: AttackCase, source: Path, output: Path, container_name: str) -> list[str]:
    """Build the hard-capped command used only for the explicit live probes."""

    return [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--pull",
        "never",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        str(case.pids_limit),
        "--cpus",
        str(case.cpus),
        "--memory",
        str(case.memory_bytes),
        "--memory-swap",
        str(case.memory_bytes),
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size={case.tmpfs_bytes}",
        "--user",
        "1000:1000",
        "--env",
        "HOME=/tmp",
        "--volume",
        f"{source}:/input/attack.py:ro",
        "--volume",
        f"{output}:/output:rw",
        DOCKER_IMAGE,
        "python",
        "/input/attack.py",
    ]


def run_case(case: AttackCase, work_root: Path) -> AttackRecord:
    """Run one explicitly requested live probe and always remove its container."""

    case_root = work_root / case.name
    case_root.mkdir(parents=True, exist_ok=True)
    source = case_root / "attack.py"
    source.write_text(case.source, encoding="utf-8")
    output = case_root / "output"
    output.mkdir(exist_ok=True)
    container_name = f"manim-phase5-attack-{case.name}-{uuid4().hex[:12]}"
    command = build_docker_command(case, source, output, container_name)
    started = time.perf_counter()
    completed: subprocess.CompletedProcess[str] | None = None
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=case.timeout_seconds,
            check=False,
        )
        observed_outcome = _classify(case, completed.returncode, completed.stdout, timed_out=False)
    except subprocess.TimeoutExpired:
        timed_out = True
        observed_outcome = "sandbox_timeout"
    except OSError:
        observed_outcome = "docker_unavailable"
    finally:
        _cleanup_container(container_name)
    container_removed = _container_is_absent(container_name)
    output_safe = _output_is_safe(output)
    duration = round(time.perf_counter() - started, 6)
    returncode = completed.returncode if completed is not None else None
    passed = (
        observed_outcome == case.expected_outcome and container_removed and output_safe
    )
    return AttackRecord(
        attack=case.name,
        passed=passed,
        expected_outcome=case.expected_outcome,
        observed_outcome=observed_outcome,
        duration_seconds=duration,
        recorded_at=_utc_now(),
        command_sha256=_sha256_json(command),
        returncode=returncode,
        timed_out=timed_out,
        container_removed=container_removed,
        output_safe=output_safe,
    )


def run_live_acceptance(work_root: Path, runs_path: Path) -> dict[str, object]:
    """Resume only cases whose latest durable evidence is not a passing result."""

    completed = completed_attacks(runs_path)
    for case in ATTACK_CASES:
        if case.name in completed:
            continue
        append_record(runs_path, run_case(case, work_root))
    return summarize(read_records(runs_path))


def _case(name: str) -> AttackCase:
    try:
        return _CASE_BY_NAME[name]
    except KeyError as exc:
        raise ValueError(f"unknown attack {name}") from exc


def _classify(case: AttackCase, returncode: int, output: str, *, timed_out: bool) -> str:
    lowered = output.lower()
    if timed_out:
        return "sandbox_timeout"
    if case.name == "fork" and ("resource temporarily unavailable" in lowered or returncode != 0):
        return "sandbox_pid_limit"
    if case.name == "oom" and (returncode in {137, 139} or returncode != 0):
        return "sandbox_oom"
    if case.name == "disk" and returncode != 0:
        return "sandbox_output_limit"
    if case.name == "network" and "network-blocked" in lowered:
        return "sandbox_security_violation"
    if case.name == "path" and "path-blocked" in lowered:
        return "sandbox_security_violation"
    if case.name == "environment" and "environment-blocked" in lowered:
        return "sandbox_security_violation"
    if case.name == "symlink" and "symlink-created" in lowered:
        return "artifact_publish_failed"
    return "unexpected-success" if returncode == 0 else "unexpected-failure"


def _cleanup_container(container_name: str) -> None:
    subprocess.run(
        ["docker", "rm", "--force", container_name],
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=10,
    )


def _container_is_absent(container_name: str) -> bool:
    try:
        probe = subprocess.run(
            ["docker", "container", "inspect", container_name],
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except OSError:
        return False
    return probe.returncode != 0


def _output_is_safe(output: Path) -> bool:
    total_size = 0
    for path in output.rglob("*"):
        if path.is_symlink() or not path.is_file():
            return False
        total_size += path.stat().st_size
        if total_size > MAX_OUTPUT_BYTES:
            return False
    return True


def _sha256_json(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--runs-jsonl", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="confirm real Docker attack execution")
    args = parser.parse_args(argv)
    if not args.execute or not live_execution_enabled():
        parser.error(
            "refusing live attacks: set PHASE5_RUN_LIVE_ATTACKS=1 and pass --execute"
        )
    report = run_live_acceptance(args.work_root, args.runs_jsonl)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(rendered, encoding="utf-8")
    return 0 if report["gate_passed"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
