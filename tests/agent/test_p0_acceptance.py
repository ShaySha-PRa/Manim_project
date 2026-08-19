from pathlib import Path

from manim_workbench_api.agent.p0_acceptance import (
    CaseResult,
    evaluate_gold,
    load_gold,
    summarize,
)


def test_gold_covers_research_matrix_and_wave_slice() -> None:
    cases = {item.id: item for item in load_gold()}
    assert set(cases) == {
        "wave-packet",
        "fourier-gibbs",
        "lorenz",
        "pid",
        "csv-anomaly",
        "frenet",
        "paper-csv",
    }
    assert cases["paper-csv"].expect == "needs_confirmation"
    assert cases["csv-anomaly"].asset == "csv"
    assert cases["wave-packet"].science_keys == ("linear_superposition",)


def test_this_gold_set_needs_all_renderable_slices() -> None:
    renderable = (
        _ready("wave-packet", rendered=True),
        _ready("fourier-gibbs", rendered=True),
        _ready("lorenz", rendered=True),
        _ready("pid", rendered=True),
        _ready("csv-anomaly", rendered=True),
        _ready("frenet", rendered=False, compile_ok=True),
        _confirm("paper-csv", ok=True),
    )
    missed = summarize(renderable, render_attempted=True)
    assert missed.first_render_rate == 5 / 6
    assert missed.first_render_rate < missed.first_render_min
    assert missed.final_success_rate == 6 / 7
    assert missed.final_success_rate < missed.final_success_min
    assert not missed.meets_p0_gates

    all_pass = summarize(
        (
            _ready("wave-packet", rendered=True),
            _ready("fourier-gibbs", rendered=True),
            _ready("lorenz", rendered=True),
            _ready("pid", rendered=True),
            _ready("csv-anomaly", rendered=True),
            _ready("frenet", rendered=True),
            _confirm("paper-csv", ok=True),
        ),
        render_attempted=True,
    )
    assert all_pass.first_render_rate == 1.0
    assert all_pass.final_success_rate == 1.0
    assert all_pass.science_rate == 1.0
    assert all_pass.meets_p0_gates


def test_gold_compile_science_and_confirmation(tmp_path: Path) -> None:
    report = evaluate_gold(work_root=tmp_path, render=False)
    assert report.renderable == 6
    assert report.n == 7
    assert report.compile_ready == 6
    assert report.science_rate == 1.0
    assert report.ir_deterministic_rate == 1.0
    assert report.confirmation_pass == 1
    assert report.first_render_rate is None
    assert report.meets_compile_gates
    assert not report.meets_p0_gates
    paper = next(item for item in report.cases if item.id == "paper-csv")
    assert paper.confirmation_ok


def _ready(case_id: str, *, rendered: bool, compile_ok: bool = True) -> CaseResult:
    return CaseResult(
        id=case_id,
        expect="ready",
        outcome="ready",
        compile_ok=compile_ok,
        science_ok=True,
        ir_deterministic=True,
        security_ok=True,
        confirmation_ok=False,
        rendered=rendered,
        message="stub",
    )


def _confirm(case_id: str, *, ok: bool) -> CaseResult:
    return CaseResult(
        id=case_id,
        expect="needs_confirmation",
        outcome="needs_confirmation",
        compile_ok=False,
        science_ok=False,
        ir_deterministic=False,
        security_ok=False,
        confirmation_ok=ok,
        rendered=None,
        message="stub",
    )
