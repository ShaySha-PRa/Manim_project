from pathlib import Path

from manim_workbench_api.agent.orchestrator import run_agent
from manim_workbench_api.agent.paper_catalog import (
    lotka_csv_text,
    lotka_paper_text,
    match_paper_catalog,
)
from manim_workbench_api.compiler.manim import compile_animation_ir
from manim_workbench_contracts.intent import AgentRunOutcome, IntentDomain, ToolOp


def test_catalog_rejects_unknown_paper() -> None:
    assert match_paper_catalog("a novel undocumented hamiltonian", None) is None


def test_lotka_paper_and_csv_compile(tmp_path: Path) -> None:
    result = run_agent(
        "根据上传论文中的动力学方程和实验 CSV，模拟模型并与实验数据做动画对比。",
        csv_text=lotka_csv_text(),
        paper_text=lotka_paper_text(),
        output_root=tmp_path,
    )
    assert result.outcome is AgentRunOutcome.READY
    assert result.intent is not None
    assert result.intent.domain is IntentDomain.SCIENTIFIC_REPRODUCTION
    assert result.tool_runs[0].op is ToolOp.ODE_COMPARE
    assert result.tool_runs[0].assertions["residual_matches_tool"] is True
    assert result.tool_runs[0].asset_version is not None
    assert result.critic_report is not None
    assert result.critic_report.expression_score >= 4.2
    compiled = compile_animation_ir(result.animation_ir, result.tool_runs)
    assert "lambda" not in compiled.segments[0].source


def test_paper_without_catalog_stays_confirmation() -> None:
    result = run_agent(
        "根据上传论文中的动力学方程和实验 CSV，模拟模型并与实验数据做动画对比。",
        csv_text=lotka_csv_text(),
        paper_text="The appendix mentions an unnamed PDE with no coefficients.",
    )
    assert result.outcome is AgentRunOutcome.NEEDS_CONFIRMATION
