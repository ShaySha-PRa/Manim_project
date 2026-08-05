"""Contract tests for the opt-in, append-only Phase 5 Docker attack harness."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def load_harness() -> object:
    path = PROJECT_ROOT / "benchmarks" / "phase5" / "attack_harness.py"
    spec = importlib.util.spec_from_file_location("phase5_attack_harness", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_attack_cases_have_hard_resource_limits_and_no_live_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = load_harness()

    monkeypatch.delenv("PHASE5_RUN_LIVE_ATTACKS", raising=False)
    assert harness.live_execution_enabled() is False
    assert {case.name for case in harness.ATTACK_CASES} == {
        "loop",
        "fork",
        "oom",
        "disk",
        "network",
        "path",
        "symlink",
        "environment",
        "residual_container",
    }
    for case in harness.ATTACK_CASES:
        compile(case.source, f"attack-{case.name}.py", "exec")
        assert case.timeout_seconds <= 15
        assert case.cpus <= 0.25
        assert case.memory_bytes <= 128 * 1024 * 1024
        assert case.pids_limit <= 16
        assert case.tmpfs_bytes <= 32 * 1024 * 1024

    monkeypatch.setenv("PHASE5_RUN_LIVE_ATTACKS", "1")
    assert harness.live_execution_enabled() is True


def test_live_attack_command_forces_python_entrypoint_and_has_only_two_data_mounts(
    tmp_path: Path,
) -> None:
    harness = load_harness()
    case = next(case for case in harness.ATTACK_CASES if case.name == "path")
    source = tmp_path / "attack.py"
    output = tmp_path / "output"
    source.write_text(case.source, encoding="utf-8")
    output.mkdir()
    command = harness.build_docker_command(case, source, output, "manim-phase5-attack-path")

    entrypoint_index = command.index("--entrypoint")
    image_index = command.index(harness.DOCKER_IMAGE)
    assert command[entrypoint_index + 1] == "python"
    assert entrypoint_index < image_index
    assert command[image_index + 1 :] == ["/input/attack.py"]
    mounts = [
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value in {"--volume", "-v"}
    ]
    assert mounts == [f"{source}:/input/attack.py:ro", f"{output}:/output:rw"]
    assert "/host-canary" not in " ".join(command)


def test_docker_start_failure_cannot_masquerade_as_a_resource_limit() -> None:
    harness = load_harness()
    for case_name in ("fork", "oom", "disk"):
        case = next(case for case in harness.ATTACK_CASES if case.name == case_name)
        assert harness._classify(case, 125, "docker rejected run", timed_out=False) == (
            "docker_start_failed"
        )


def test_jsonl_is_append_only_resumable_and_rejects_forged_records(tmp_path: Path) -> None:
    harness = load_harness()
    runs_path = tmp_path / "runs.jsonl"
    first = harness.AttackRecord.success("loop", 0.2, "sandbox_timeout")
    second = harness.AttackRecord.failure("loop", 0.3, "unexpected-success")

    harness.append_record(runs_path, first)
    harness.append_record(runs_path, second)

    assert len(runs_path.read_text(encoding="utf-8").splitlines()) == 2
    assert harness.completed_attacks(runs_path) == set()
    assert harness.latest_records(harness.read_records(runs_path))["loop"]["passed"] is False

    forged = json.dumps({"attack": "loop", "passed": True}) + "\n"
    runs_path.write_text(runs_path.read_text(encoding="utf-8") + forged, encoding="utf-8")
    with pytest.raises(ValueError, match="record_type"):
        harness.read_records(runs_path)


def test_summary_fails_closed_for_missing_or_failed_attack_evidence(tmp_path: Path) -> None:
    harness = load_harness()
    runs_path = tmp_path / "runs.jsonl"
    for case in harness.ATTACK_CASES:
        harness.append_record(
            runs_path,
            harness.AttackRecord.success(case.name, 0.1, case.expected_outcome),
        )

    report = harness.summarize(harness.read_records(runs_path))
    assert report["gate_passed"] is True
    assert report["effective_record_count"] == len(harness.ATTACK_CASES)
    assert report["duration_median_seconds"] == 0.1
    assert report["duration_max_seconds"] == 0.1

    with pytest.raises(ValueError, match="missing"):
        harness.summarize(harness.read_records(runs_path)[:-1])


def test_detected_symlink_is_accepted_as_rejected_malicious_output_evidence(tmp_path: Path) -> None:
    harness = load_harness()
    runs_path = tmp_path / "runs.jsonl"
    for case in harness.ATTACK_CASES:
        record = harness.AttackRecord.success(case.name, 0.1, case.expected_outcome)
        if case.name == "symlink":
            record = harness.AttackRecord(
                **{
                    **record.as_dict(),
                    "output_safe": False,
                    "artifact_rejected": True,
                    "passed": True,
                }
            )
        harness.append_record(runs_path, record)

    report = harness.summarize(harness.read_records(runs_path))
    assert report["gate_passed"] is True
    assert report["unmitigated_output_attacks"] == []


def test_symlink_evidence_comes_from_the_product_artifact_validation_boundary(
    tmp_path: Path,
) -> None:
    harness = load_harness()
    output = tmp_path / "output"
    output.mkdir()
    (output / "link").symlink_to("/etc/passwd")

    assert harness.artifact_validator_rejected(output) is True
