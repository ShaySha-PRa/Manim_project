from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from manim_workbench_api.code_generation.prompts import build_code_generation_messages
from manim_workbench_api.code_generation.template_compiler import compile_deterministic_template
from manim_workbench_api.quality.temporal import analyze_temporal_quality
from manim_workbench_contracts import (
    CodeGenerationCategory,
    ContentPlanScene,
    ContentPlanVersion,
    FormulaStep,
)


def plan(target_duration_seconds: int = 90) -> ContentPlanVersion:
    return ContentPlanVersion(
        id=uuid4(),
        project_id=uuid4(),
        owner_id=uuid4(),
        version=1,
        parent_version_id=None,
        created_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        schema_version="1.1",
        title="二次函数",
        audience="high_school",
        language="zh-CN",
        target_duration_seconds=target_duration_seconds,
        derivation_style="step_by_step",
        explicit_assumptions=(),
        ambiguities=(),
        scenes=(
            ContentPlanScene(
                scene_number=1,
                teaching_goal="解释抛物线顶点",
                formula_steps=(FormulaStep(expression="y=x²", explanation="观察图像"),),
                visual_intent="绘制坐标轴和抛物线",
                narration_placeholder="说明顶点和对称轴",
            ),
        ),
    )


def test_code_prompt_makes_target_duration_a_timeline_requirement() -> None:
    messages = build_code_generation_messages(
        plan(90), CodeGenerationCategory.FUNCTION_VISUALIZATION
    )
    combined = "\n".join(message.content for message in messages)
    assert "Target timeline: 90 seconds" in combined
    assert "81.0 to 99.0 seconds" in combined
    assert "at least 23 active self.play calls" in combined
    assert "calculate the sum of every explicit" in combined
    assert "Do not pad" in combined
    assert "Preview and Final" in combined


def test_deterministic_fallback_implements_the_requested_timeline() -> None:
    source = compile_deterministic_template(
        plan(90), CodeGenerationCategory.FUNCTION_VISUALIZATION
    ).code
    report = analyze_temporal_quality(source, target_duration_seconds=90)
    assert report.estimated_duration_seconds == 90
    assert max(event.duration_seconds or 0 for event in report.events) <= 4
    assert not {item.code.value for item in report.diagnostics} & {
        "duration_too_short",
        "duration_too_long",
        "terminal_wait_padding",
    }
