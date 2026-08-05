from __future__ import annotations

from uuid import uuid4

import pytest
from manim_workbench_api.content_plans.errors import ContentPlanSemanticError
from manim_workbench_api.content_plans.validation import validate_content_plan_response
from manim_workbench_contracts import (
    Audience,
    ContentPlanDraft,
    ContentPlanGenerationRequest,
    ContentPlanLimitation,
    ContentPlanModelResponse,
    ContentPlanOutcome,
    ContentPlanScene,
    DerivationStyle,
    FormulaStep,
    Language,
)


def request(
    *,
    audience: Audience | None = Audience.HIGH_SCHOOL,
    language: Language = Language.ZH_CN,
    target_duration_seconds: int | None = 60,
    derivation_style: DerivationStyle | None = DerivationStyle.STEP_BY_STEP,
) -> ContentPlanGenerationRequest:
    return ContentPlanGenerationRequest(
        project_id=uuid4(),
        owner_id=uuid4(),
        prompt_version_id=uuid4(),
        audience=audience,
        language=language,
        target_duration_seconds=target_duration_seconds,
        derivation_style=derivation_style,
    )


def ready_response(
    *,
    scenes: tuple[ContentPlanScene, ...] | None = None,
    audience: Audience = Audience.HIGH_SCHOOL,
    language: Language = Language.ZH_CN,
    target_duration_seconds: int = 60,
    derivation_style: DerivationStyle = DerivationStyle.STEP_BY_STEP,
    explicit_assumptions: tuple[str, ...] = (),
    ambiguities: tuple[str, ...] = (),
) -> ContentPlanModelResponse:
    return ContentPlanModelResponse(
        outcome=ContentPlanOutcome.READY,
        plan=ContentPlanDraft(
            schema_version="1.1",
            title="平方函数",
            audience=audience,
            language=language,
            target_duration_seconds=target_duration_seconds,
            derivation_style=derivation_style,
            explicit_assumptions=explicit_assumptions,
            ambiguities=ambiguities,
            scenes=scenes
            or (
                ContentPlanScene(
                    scene_number=1,
                    teaching_goal="从定义推导平方函数。",
                    formula_steps=(
                        FormulaStep(expression="f(x)=x^2", explanation="给出函数定义。"),
                        FormulaStep(expression="f(2)=4", explanation="代入一个输入。"),
                    ),
                    visual_intent="显示坐标轴、定义域 x 属于实数，并突出开口向上的最小值行为。",
                    narration_placeholder="观察函数图像。",
                ),
            ),
        ),
    )


def test_accepts_semantically_complete_ready_plan() -> None:
    response = ready_response()

    assert validate_content_plan_response(response, request(), "请公式推导平方函数") is response


def test_derivation_about_a_function_does_not_require_graph_semantics() -> None:
    response = ready_response(
        scenes=(
            ContentPlanScene(
                scene_number=1,
                teaching_goal="推导链式法则。",
                formula_steps=(
                    FormulaStep(expression="y=f(u)", explanation="定义外函数。"),
                    FormulaStep(expression="dy/dx=(dy/du)(du/dx)", explanation="组合变化率。"),
                ),
                visual_intent="突出内外函数的依赖关系。",
                narration_placeholder="解释两级变化率。",
            ),
        )
    )

    assert (
        validate_content_plan_response(
            response,
            request(),
            "用内外函数的变化率推导链式法则。",
        )
        is response
    )


def test_rejects_non_contiguous_scene_numbers() -> None:
    response = ready_response(
        scenes=(
            ContentPlanScene(
                scene_number=1,
                teaching_goal="定义函数。",
                formula_steps=(FormulaStep(expression="f(x)=x^2", explanation="定义。"),),
                visual_intent="显示坐标轴。",
                narration_placeholder="第一场。",
            ),
            ContentPlanScene(
                scene_number=3,
                teaching_goal="计算函数值。",
                formula_steps=(FormulaStep(expression="f(2)=4", explanation="代入。"),),
                visual_intent="标记坐标点。",
                narration_placeholder="第二场。",
            ),
        )
    )

    with pytest.raises(ContentPlanSemanticError, match="scene_number"):
        validate_content_plan_response(response, request(), "请公式推导平方函数")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("audience", Audience.MIDDLE_SCHOOL),
        ("language", Language.EN_US),
        ("target_duration_seconds", 90),
        ("derivation_style", DerivationStyle.VISUAL_INTUITION),
    ],
)
def test_rejects_explicit_request_fields_changed_by_model(field: str, value: object) -> None:
    response = ready_response(**{field: value})

    with pytest.raises(ContentPlanSemanticError, match=field):
        validate_content_plan_response(response, request(), "请公式推导平方函数")


def test_rejects_explicit_assumption_removed_by_model() -> None:
    requested = request()
    requested = requested.model_copy(
        update={"explicit_assumptions": ("学习者已经理解函数定义。",)}
    )

    with pytest.raises(ContentPlanSemanticError, match="explicit_assumptions"):
        validate_content_plan_response(
            ready_response(explicit_assumptions=()),
            requested,
            "请公式推导平方函数",
        )


@pytest.mark.parametrize(
    "expression",
    (
        "```python\\nprint(1)\\n```",
        "<script>alert(1)</script>",
        "rm -rf /tmp/example",
        "f(x)=(x+1",
        r"\\left(x+1",
    ),
)
def test_rejects_unsafe_or_unbalanced_formula_text(expression: str) -> None:
    response = ready_response(
        scenes=(
            ContentPlanScene(
                scene_number=1,
                teaching_goal="检查公式。",
                formula_steps=(
                    FormulaStep(expression=expression, explanation="第一步。"),
                    FormulaStep(expression="x=1", explanation="第二步。"),
                ),
                visual_intent="显示坐标轴、定义域和递增行为。",
                narration_placeholder="检查公式。",
            ),
        )
    )

    with pytest.raises(ContentPlanSemanticError, match="formula"):
        validate_content_plan_response(response, request(), "请公式推导函数")


def test_rejects_derivation_prompt_with_fewer_than_two_formula_steps() -> None:
    response = ready_response(
        scenes=(
            ContentPlanScene(
                scene_number=1,
                teaching_goal="给出结论。",
                formula_steps=(FormulaStep(expression="y=x", explanation="结论。"),),
                visual_intent="显示坐标轴。",
                narration_placeholder="只有一步。",
            ),
        )
    )

    with pytest.raises(ContentPlanSemanticError, match="derivation"):
        validate_content_plan_response(response, request(), "请公式推导一次函数")


def test_rejects_function_visualization_without_domain_or_key_behavior() -> None:
    response = ready_response(
        scenes=(
            ContentPlanScene(
                scene_number=1,
                teaching_goal="观察函数。",
                formula_steps=(FormulaStep(expression="y=x^2", explanation="定义。"),),
                visual_intent="显示坐标轴和函数曲线。",
                narration_placeholder="观察图像。",
            ),
        )
    )

    with pytest.raises(ContentPlanSemanticError, match="function_visualization"):
        validate_content_plan_response(response, request(), "请可视化函数图像")


def test_rejects_ready_plan_with_unresolved_ambiguities() -> None:
    response = ready_response(ambiguities=("尚未确定受众。",))

    with pytest.raises(ContentPlanSemanticError, match="ambiguities"):
        validate_content_plan_response(response, request(), "请公式推导平方函数")


def test_accepts_ready_plan_with_explicit_noncritical_visual_ambiguity() -> None:
    response = ready_response(ambiguities=("用户未指定颜色，采用默认高对比度配色。",))

    assert validate_content_plan_response(response, request(), "请公式推导平方函数") is response


def test_function_visualization_aggregates_domain_and_behavior_across_scene_fields() -> None:
    response = ready_response(
        derivation_style=DerivationStyle.VISUAL_INTUITION,
        scenes=(
            ContentPlanScene(
                scene_number=1,
                teaching_goal="比较曲线上方和下方的面积。",
                formula_steps=(
                    FormulaStep(
                        expression="x\\in[0,2\\pi]",
                        explanation="固定可视化区间。",
                    ),
                ),
                visual_intent="绘制正弦曲线并填充正负面积。",
                narration_placeholder="累计带符号面积后定积分为零。",
            ),
        ),
    )

    assert (
        validate_content_plan_response(
            response,
            request(derivation_style=DerivationStyle.VISUAL_INTUITION),
            "展示正弦函数在给定区间的面积。",
        )
        is response
    )


def test_requires_reversible_audience_assumption_when_audience_was_not_requested() -> None:
    response = ready_response()

    with pytest.raises(ContentPlanSemanticError, match="audience"):
        validate_content_plan_response(
            response,
            request(audience=None),
            "请制作平方函数的教学动画",
        )


def test_rejects_nonreversible_audience_assumption_when_audience_was_not_requested() -> None:
    response = ready_response(explicit_assumptions=("假设受众为高中生。",))

    with pytest.raises(ContentPlanSemanticError, match="audience"):
        validate_content_plan_response(
            response,
            request(audience=None),
            "请制作平方函数的教学动画",
        )


def test_accepts_reversible_audience_assumption_when_audience_was_not_requested() -> None:
    response = ready_response(explicit_assumptions=("假设受众为高中生，可调整。",))

    assert (
        validate_content_plan_response(
            response,
            request(audience=None),
            "请制作平方函数的教学动画",
        )
        is response
    )


def test_rejects_ready_outcome_for_first_version_unsupported_scope() -> None:
    response = ready_response()

    with pytest.raises(ContentPlanSemanticError, match="unsupported"):
        validate_content_plan_response(response, request(), "请为线性代数矩阵乘法制作动画")


def test_accepts_structured_unsupported_response_for_first_version_scope() -> None:
    response = ContentPlanModelResponse(
        outcome=ContentPlanOutcome.UNSUPPORTED,
        limitations=(
            ContentPlanLimitation(
                code="linear_algebra",
                message="线性代数不在首版支持范围内。",
                supported_alternative="可以制作函数可视化。",
            ),
        ),
    )

    assert (
        validate_content_plan_response(response, request(), "请为线性代数矩阵乘法制作动画")
        is response
    )
