from pathlib import Path

from manim_workbench_api.agent.ir_repair import repair_animation_ir
from manim_workbench_api.agent.orchestrator import run_agent
from manim_workbench_api.content_plans.models import ProviderMessage, ProviderResult
from manim_workbench_api.quality.semantic.critic import CRITIC_SYSTEM_PROMPT, evaluate_expression
from manim_workbench_contracts import CriticFinding
from manim_workbench_contracts.animation_ir import (
    AnimAssertion,
    AnimationIR,
    AnimObject,
    AssertionType,
    CameraOpKind,
    ObjectType,
    TimelineOp,
    TimelineOpKind,
    VisualPattern,
)
from manim_workbench_contracts.intent import CriticAnswer


class _FakeCritic:
    def generate(self, messages: tuple[ProviderMessage, ...]) -> ProviderResult:
        self.messages = messages
        return ProviderResult(
            content='{"answers":[{"id":"has_title","answer":"yes"}],"findings":[]}',
            model="fake-critic",
        )


def test_fourier_critic_scores_expression_and_repairs_missing_zoom(tmp_path: Path) -> None:
    result = run_agent("展示傅里叶级数逐渐逼近方波，并放大 Gibbs 现象", output_root=tmp_path)
    assert result.critic_report is not None
    assert result.critic_report.expression_score >= 4.2
    assert result.repair_count == 0
    stripped = result.animation_ir.model_copy(update={"camera": ()})
    report = evaluate_expression(
        stripped, result.tool_runs, "from manim import Scene\nallow_pickle=False\n"
    )
    assert any(item.code == "missing_zoom" for item in report.findings)
    repaired = repair_animation_ir(stripped, report.findings)
    assert any(item.op is CameraOpKind.ZOOM for item in repaired.camera)


def test_vlm_provider_must_be_json_only(tmp_path: Path) -> None:
    result = run_agent(
        "展示二维波动方程中两个波包碰撞后的干涉过程",
        output_root=tmp_path,
        critic_provider=_FakeCritic(),
    )
    assert result.critic_report is not None
    assert result.critic_report.vlm_used is True
    assert result.critic_report.questions[0].evidence == "vlm"
    assert "Manim" in CRITIC_SYSTEM_PROMPT
    assert result.critic_report.questions[0].answer is CriticAnswer.YES


def test_repair_adds_title_when_missing() -> None:
    ir = AnimationIR(
        domain="control",
        goal="compare",
        pattern=VisualPattern.COMPARISON,
        objects=(AnimObject(id="y", type=ObjectType.GRAPH),),
        timeline=(TimelineOp(op=TimelineOpKind.COMPARE, duration=1.0),),
        assertions=(AnimAssertion(type=AssertionType.METRIC_MATCH),),
    )
    repaired = repair_animation_ir(
        ir,
        (CriticFinding(code="missing_title", message="缺少标题", repairable=True),),
    )
    assert repaired.objects[0].id == "title"
