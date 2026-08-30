from __future__ import annotations

from uuid import uuid4

from manim_workbench_api.workflows.director.prompts import (
    DIRECTOR_PROMPT_TEMPLATE_VERSION,
    build_director_messages,
    build_director_repair_messages,
)
from manim_workbench_contracts import (
    DirectorPlanRequest,
    Language,
    WorkflowStylePreset,
)


def _request() -> DirectorPlanRequest:
    return DirectorPlanRequest(
        project_id=uuid4(),
        objective="解释 Lorenz 系统，并展示真实计算得到的初值敏感性。",
        language=Language.ZH_CN,
        target_duration_seconds=120,
        style_preset=WorkflowStylePreset.DARK_SCIENTIFIC,
        idempotency_key="00000000000000000000000000000001",
    )


def test_director_prompt_separates_paths_and_forbids_execution_authority() -> None:
    messages = build_director_messages(_request())
    system = messages[0].content
    user = messages[1].content

    assert DIRECTOR_PROMPT_TEMPLATE_VERSION == "workflow-director-v1"
    assert "ContentPlan" in system
    assert "IntentSpec" in system
    assert "AnimationIR" in system
    assert "2" in system and "8" in system
    assert "Manim Python" in system
    assert "不得调用工具" in system
    assert "asset_required" in system
    assert "needs_confirmation" in system
    assert "<untrusted_workflow_objective_json>" in user
    assert "解释 Lorenz 系统" in user
    assert str(_request().project_id) not in user


def test_director_repair_prompt_contains_only_bounded_diagnostic() -> None:
    messages = build_director_repair_messages(
        _request(), "director_invalid_schema: scenes must contain 2 to 8 items"
    )
    assert len(messages) == 2
    assert "director_invalid_schema" in messages[1].content
    assert "修复" in messages[1].content
    assert len(messages[1].content) < 25_000
