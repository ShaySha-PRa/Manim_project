from pathlib import Path

from manim_workbench_api.agent.p2_acceptance import (
    BENCH_MAX,
    BENCH_MIN,
    evaluate_p2_benchmark,
    load_p2_benchmark,
)


def test_p2_benchmark_has_one_hundred_to_three_hundred_prompts() -> None:
    cases = load_p2_benchmark()
    assert BENCH_MIN <= len(cases) <= BENCH_MAX
    families = {item.family for item in cases}
    assert {"wave", "fourier", "paper", "paper-unknown", "csv-missing"} <= families
    assert any(item.asset == "paper_csv" for item in cases)


def test_p2_benchmark_meets_science_fail_and_cross_backend(tmp_path: Path) -> None:
    report = evaluate_p2_benchmark(work_root=tmp_path)
    assert report.n >= BENCH_MIN
    assert report.science_rate >= report.science_min
    assert report.fail_rate < report.fail_max
    assert report.cross_backend_rate == 1.0
    assert report.meets_p2_gates
    assert report.as_dict()["external_user_study"] is False
