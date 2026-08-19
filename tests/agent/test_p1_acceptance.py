from pathlib import Path

from manim_workbench_api.agent.p1_acceptance import (
    GOLD_MAX,
    GOLD_MIN,
    evaluate_p1_gold,
    load_p1_gold,
)


def test_p1_gold_has_fifty_to_one_hundred_prompts() -> None:
    cases = load_p1_gold()
    assert GOLD_MIN <= len(cases) <= GOLD_MAX
    families = {item.family for item in cases}
    assert {"wave", "fourier", "paper", "paper-unknown", "csv-missing"} <= families
    assert any(item.asset == "paper_csv" for item in cases)


def test_p1_gold_meets_expression_repair_and_provenance(tmp_path: Path) -> None:
    report = evaluate_p1_gold(work_root=tmp_path)
    assert report.n >= GOLD_MIN
    assert report.expression_mean >= report.expression_min
    assert report.repair_mean <= report.repair_mean_max
    assert report.provenance_rate == 1.0
    assert report.meets_p1_gates
