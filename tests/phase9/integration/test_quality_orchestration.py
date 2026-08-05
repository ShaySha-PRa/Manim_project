from datetime import datetime, timezone
from uuid import uuid4

from manim_workbench_api.quality.orchestration import diagnose_content_plan_timeline
from manim_workbench_api.quality.temporal import MediaTiming
from manim_workbench_contracts import (
    Audience,
    ContentPlanScene,
    ContentPlanVersion,
    DerivationStyle,
    FormulaStep,
    Language,
    QualityDiagnosticCode,
)


def _plan(target: int = 90) -> ContentPlanVersion:
    return ContentPlanVersion(
        id=uuid4(),
        project_id=uuid4(),
        owner_id=uuid4(),
        version=1,
        parent_version_id=None,
        created_at=datetime.now(timezone.utc),
        schema_version="1.1",
        title="一次函数",
        audience=Audience.HIGH_SCHOOL,
        language=Language.ZH_CN,
        target_duration_seconds=target,
        derivation_style=DerivationStyle.VISUAL_INTUITION,
        explicit_assumptions=(),
        ambiguities=(),
        scenes=(
            ContentPlanScene(
                scene_number=1,
                teaching_goal="理解斜率。",
                formula_steps=(FormulaStep(expression="y=x", explanation="观察直线。"),),
                visual_intent="在坐标系绘制定义域。",
                narration_placeholder="解释斜率变化。",
            ),
        ),
    )


def _source(duration: float) -> str:
    return (
        "from manim import MathTex, Scene, Write\n\n"
        "class GeneratedScene(Scene):\n"
        "    def construct(self):\n"
        "        formula = MathTex('y=x')\n"
        f"        self.play(Write(formula), run_time={duration})\n"
    )


def test_content_plan_target_reaches_static_and_actual_duration_diagnostics() -> None:
    temporal, diagnostics = diagnose_content_plan_timeline(
        source_code=_source(9.6),
        content_plan=_plan(90),
        actual_media=MediaTiming(duration_seconds=9.6, frame_rate=30, frame_count=288),
    )

    assert temporal.target_duration_seconds == 90
    assert temporal.estimated_duration_seconds == 9.6
    assert temporal.actual_duration_seconds == 9.6
    assert [item.code for item in diagnostics].count(QualityDiagnosticCode.DURATION_TOO_SHORT) == 2


def test_same_inputs_produce_identical_sanitized_diagnostics() -> None:
    first = diagnose_content_plan_timeline(
        source_code=_source(90),
        content_plan=_plan(90),
        actual_media=MediaTiming(duration_seconds=90, frame_rate=30, frame_count=2700),
    )
    second = diagnose_content_plan_timeline(
        source_code=_source(90),
        content_plan=_plan(90),
        actual_media=MediaTiming(duration_seconds=90, frame_rate=30, frame_count=2700),
    )

    assert first[0].estimated_duration_seconds == second[0].estimated_duration_seconds == 90
    assert first[1] == second[1]
