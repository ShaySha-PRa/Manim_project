from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from benchmarks.phase9.acceptance import (
    AcceptanceFailure,
    build_terminal_records,
    evaluate_acceptance,
    load_corpus,
    load_metrics_baseline,
)

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "benchmarks" / "phase9" / "golden_corpus.json"
BASELINE = ROOT / "benchmarks" / "phase9" / "baseline_metrics.json"


def test_offline_golden_corpus_has_thirty_cases_and_sixty_terminal_records() -> None:
    corpus = load_corpus(CORPUS)
    records = build_terminal_records(corpus)

    assert len(corpus["cases"]) == 30
    assert len(records) == 60
    assert {record["profile"] for record in records} == {"preview", "final"}
    assert {case["category"] for case in corpus["cases"]} == {
        "formula_derivation",
        "function_visualization",
    }
    coverage = {tag for case in corpus["cases"] for tag in case["coverage"]}
    assert {
        "duration_90_to_9_6",
        "duration_too_long",
        "long_static_padding",
        "blank_frame",
        "object_out_of_bounds",
        "object_overlap",
        "text_too_small",
        "cjk_glyph_missing",
        "key_formula_missing",
        "object_missing",
        "animation_order_mismatch",
        "malformed_media",
        "repeated_diagnostic_signature",
        "two_repair_cap",
        "preview_final_one_frame",
        "owner_isolation",
        "determinism",
        "performance",
        "version_regression",
    } <= coverage


def test_frozen_corpus_passes_the_independent_baseline_gate() -> None:
    corpus = load_corpus(CORPUS)

    report = evaluate_acceptance(
        corpus=corpus,
        records=build_terminal_records(corpus),
        baseline=load_metrics_baseline(BASELINE),
    )

    assert report["status"] == "passed"
    assert report["metrics"]["terminal_records"] == 60
    assert report["metrics"]["golden_cases"] == 30
    assert report["metrics"]["deterministic_pairs"] == 30


@pytest.mark.parametrize(
    ("case_id", "profile", "patch", "expected_code"),
    [
        (
            "F01",
            "preview",
            {"actual_duration_seconds": 9.6, "diagnostic_codes": []},
            "duration_diagnostic_missing",
        ),
        (
            "F03",
            "preview",
            {"longest_static_seconds": 18.1, "diagnostic_codes": []},
            "static_padding_undetected",
        ),
        ("G06", "preview", {"repair_count": 3}, "repair_budget_exceeded"),
        ("G08", "final", {"frame_count": 2702}, "preview_final_frame_mismatch"),
        (
            "F14",
            "final",
            {"actual_duration_seconds": 90.1},
            "preview_final_timeline_mismatch",
        ),
        (
            "F13",
            "preview",
            {"repeated_signature": True, "terminal_status": "repair_required"},
            "repeat_signature_loop",
        ),
        ("F04", "preview", {"terminal_status": "passed"}, "severe_diagnostic_passed"),
        ("F11", "preview", {"replay_signature": "changed"}, "determinism_mismatch"),
        ("F15", "preview", {"analysis_elapsed_ms": 2_501}, "performance_budget_exceeded"),
        ("G12", "preview", {"provenance_version": "phase9-v2"}, "version_regression_detected"),
    ],
)
def test_acceptance_rejects_quality_gate_bypass(
    case_id: str, profile: str, patch: dict[str, object], expected_code: str
) -> None:
    corpus = load_corpus(CORPUS)
    records = build_terminal_records(corpus)
    for record in records:
        if record["case_id"] == case_id and record["profile"] == profile:
            record.update(patch)

    with pytest.raises(AcceptanceFailure, match=expected_code):
        evaluate_acceptance(
            corpus=corpus,
            records=records,
            baseline=load_metrics_baseline(BASELINE),
        )


def test_acceptance_rejects_cross_owner_access_and_metric_regression() -> None:
    corpus = load_corpus(CORPUS)
    records = build_terminal_records(corpus)
    records[0]["cross_owner_access"] = "allowed"
    baseline = load_metrics_baseline(BASELINE)

    with pytest.raises(AcceptanceFailure, match="owner_isolation_failed"):
        evaluate_acceptance(corpus=corpus, records=records, baseline=baseline)

    records = build_terminal_records(corpus)
    baseline["minimum_metrics"]["quality_pass_rate_percent"] = 100.1
    with pytest.raises(AcceptanceFailure, match="metric_regression"):
        evaluate_acceptance(corpus=corpus, records=records, baseline=baseline)


def test_corpus_rejects_secrets_and_absolute_paths_without_echoing_them(tmp_path: Path) -> None:
    secret_marker = "s" + "k-" + "notarealcredential"
    payload = {
        "schema_version": "1.0",
        "cases": [{"id": "F01", "artifact_ref": f"/host/private/{secret_marker}"}],
    }
    corpus = tmp_path / "unsafe.json"
    corpus.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AcceptanceFailure) as caught:
        load_corpus(corpus)

    assert "unsafe_corpus_content" in str(caught.value)
    assert secret_marker not in str(caught.value)
    assert "/host/private" not in str(caught.value)


def test_acceptance_cli_is_offline_and_emits_only_redacted_summary() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/phase9_acceptance.py"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    report = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert report["status"] == "passed"
    assert report["metrics"]["terminal_records"] == 60
    assert "sk-" not in completed.stdout.lower()
    assert "/home/" not in completed.stdout
