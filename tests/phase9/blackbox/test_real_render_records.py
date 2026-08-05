from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RECORDS = ROOT / "benchmarks/phase9/real_terminal_records.json"
REPORT = ROOT / "benchmarks/phase9/real_acceptance_report.json"


def test_real_acceptance_contains_30_complete_preview_final_pairs() -> None:
    records = json.loads(RECORDS.read_text(encoding="utf-8"))["records"]
    pairs = {(item["case_id"], item["profile"]) for item in records}

    assert len(records) == 60
    assert len({item["case_id"] for item in records}) == 30
    assert all(
        (case_id, profile) in pairs for case_id, _ in pairs for profile in ("preview", "final")
    )


def test_real_acceptance_meets_duration_visual_and_timeline_gates() -> None:
    records = json.loads(RECORDS.read_text(encoding="utf-8"))["records"]
    by_case: dict[str, dict[str, dict[str, object]]] = {}
    for item in records:
        by_case.setdefault(item["case_id"], {})[item["profile"]] = item
        assert 81 <= item["actual_duration_seconds"] <= 99
        assert item["terminal_status"] == "passed"
        assert item["diagnostic_codes"] == []

    for pair in by_case.values():
        preview = pair["preview"]
        final = pair["final"]
        preview_seconds = preview["frame_count"] / preview["frame_rate"]
        final_seconds = final["frame_count"] / final["frame_rate"]
        assert abs(preview_seconds - final_seconds) <= 1 / max(
            preview["frame_rate"], final["frame_rate"]
        )

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["terminal_renders"] == 60
    assert report["failures"] == []
