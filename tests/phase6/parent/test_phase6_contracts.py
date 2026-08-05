from __future__ import annotations

from uuid import uuid4

import pytest
from manim_workbench_api.content_plans.models import ProviderResult
from manim_workbench_contracts import (
    Audience,
    ClarificationField,
    ClarificationQuestion,
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
from pydantic import ValidationError


def draft() -> ContentPlanDraft:
    return ContentPlanDraft(
        schema_version="1.1",
        title="一次函数图像",
        audience=Audience.HIGH_SCHOOL,
        language=Language.ZH_CN,
        target_duration_seconds=60,
        derivation_style=DerivationStyle.VISUAL_INTUITION,
        explicit_assumptions=("学习者理解坐标系。",),
        ambiguities=(),
        scenes=(
            ContentPlanScene(
                scene_number=1,
                teaching_goal="观察斜率变化",
                formula_steps=(FormulaStep(expression="y=kx", explanation="固定截距。"),),
                visual_intent="显示坐标轴并改变 k。",
                narration_placeholder="比较正负斜率。",
            ),
        ),
    )


def test_generation_request_forbids_provider_overrides() -> None:
    with pytest.raises(ValidationError, match="api_key"):
        ContentPlanGenerationRequest(
            project_id=uuid4(),
            owner_id=uuid4(),
            prompt_version_id=uuid4(),
            api_key="must-not-be-accepted",
        )


def test_ready_response_requires_only_plan() -> None:
    response = ContentPlanModelResponse(outcome=ContentPlanOutcome.READY, plan=draft())
    assert response.plan is not None

    with pytest.raises(ValidationError, match="ready requires only plan"):
        ContentPlanModelResponse(
            outcome=ContentPlanOutcome.READY,
            plan=draft(),
            clarifications=(
                ClarificationQuestion(
                    field=ClarificationField.AUDIENCE,
                    question="受众是谁？",
                ),
            ),
        )


def test_clarification_and_unsupported_are_structured() -> None:
    clarification = ContentPlanModelResponse(
        outcome=ContentPlanOutcome.NEEDS_CLARIFICATION,
        clarifications=(
            ClarificationQuestion(
                field=ClarificationField.MATHEMATICAL_INTENT,
                question="需要代数推导还是几何直观？",
                options=("代数推导", "几何直观"),
            ),
        ),
    )
    unsupported = ContentPlanModelResponse(
        outcome=ContentPlanOutcome.UNSUPPORTED,
        limitations=(
            ContentPlanLimitation(
                code="user_asset_required",
                message="首版不读取用户素材。",
                supported_alternative="改用内置几何对象。",
            ),
        ),
    )
    assert clarification.plan is None
    assert unsupported.limitations[0].supported_alternative


def test_phase6_draft_requires_explicit_style_and_ambiguities() -> None:
    payload = draft().model_dump(mode="json")
    payload.pop("derivation_style")
    with pytest.raises(ValidationError, match="derivation_style"):
        ContentPlanDraft.model_validate(payload)


def test_provider_result_bounds_untrusted_content() -> None:
    with pytest.raises(ValidationError, match="200000"):
        ProviderResult(content="x" * 200_001, model="deepseek-v4-flash")


def test_contract_supports_general_audience_gold_persona() -> None:
    assert Audience.GENERAL_AUDIENCE.value == "general_audience"
