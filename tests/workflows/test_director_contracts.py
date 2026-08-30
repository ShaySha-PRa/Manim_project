from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from manim_workbench_contracts import (
    DirectorConfirmation,
    DirectorDraft,
    DirectorGlobalBriefDraft,
    DirectorPlan,
    DirectorPlanRequest,
    DirectorPlanStatus,
    DirectorSceneDraft,
    Language,
    ScenePipelineMode,
    WorkflowStylePreset,
)
from pydantic import ValidationError


def _scene(index: int, *, duration: int = 30) -> DirectorSceneDraft:
    return DirectorSceneDraft(
        title=f"Scene {index}",
        prompt=f"Explain scientific scene {index}",
        pipeline_mode=ScenePipelineMode.AUTO,
        target_duration_seconds=duration,
        asset_requirements=(),
        semantic_summary=f"Scene {index} summary",
    )


def _draft(*scenes: DirectorSceneDraft, duration: int = 60) -> DirectorDraft:
    return DirectorDraft(
        global_brief=DirectorGlobalBriefDraft(
            title="A bounded scientific story",
            language=Language.ZH_CN,
            target_duration_seconds=duration,
            style_preset=WorkflowStylePreset.DARK_SCIENTIFIC,
            background="#10131a",
            palette=("#4c8dff", "#ffd84c"),
        ),
        scenes=scenes or (_scene(1), _scene(2)),
        assumptions=("Use only verified inputs.",),
        confirmations=(),
    )


def _request() -> DirectorPlanRequest:
    return DirectorPlanRequest(
        project_id=uuid4(),
        objective="Create a complete explanation of a bounded scientific process.",
        language=Language.ZH_CN,
        target_duration_seconds=60,
        style_preset=WorkflowStylePreset.DARK_SCIENTIFIC,
        asset_version_ids=(),
        idempotency_key="director-contract-request-0001",
    )


def test_director_request_and_draft_are_strict_frozen_and_round_trip() -> None:
    request = _request()
    draft = _draft()

    assert DirectorPlanRequest.model_validate_json(request.model_dump_json()) == request
    assert DirectorDraft.model_validate_json(draft.model_dump_json()) == draft
    with pytest.raises(ValidationError, match="extra"):
        DirectorPlanRequest.model_validate({**request.model_dump(), "escape": True})
    with pytest.raises(ValidationError, match="frozen"):
        draft.scenes = ()  # type: ignore[misc]


@pytest.mark.parametrize("count", [1, 9])
def test_director_draft_requires_two_to_eight_scenes(count: int) -> None:
    with pytest.raises(ValidationError):
        _draft(*(_scene(index) for index in range(count)), duration=max(30, count * 30))


@pytest.mark.parametrize("duration", [14, 121])
def test_director_scene_duration_is_bounded(duration: int) -> None:
    with pytest.raises(ValidationError):
        _scene(1, duration=duration)


def test_director_draft_rejects_mismatched_or_unbounded_total_duration() -> None:
    with pytest.raises(ValidationError, match="sum"):
        _draft(_scene(1), _scene(2), duration=90)
    with pytest.raises(ValidationError):
        _draft(*(_scene(index, duration=120) for index in range(6)), duration=600)


def test_confirmation_and_plan_status_require_consistent_terminal_payload() -> None:
    confirmation = DirectorConfirmation(
        code="pipeline_confirmation_required",
        message="Choose the intended scene pipeline.",
        scene_position=2,
        kind="needs_confirmation",
    )
    request = _request()
    now = datetime.now(timezone.utc)
    plan = DirectorPlan(
        id=uuid4(),
        project_id=request.project_id,
        owner_id=uuid4(),
        request=request,
        status=DirectorPlanStatus.READY,
        draft=_draft().model_copy(update={"confirmations": (confirmation,)}),
        cache_key="a" * 64,
        attempt_count=1,
        provider_model="director-test-provider",
        prompt_template_version="workflow-director-v1",
        input_sha256="b" * 64,
        output_sha256="c" * 64,
        error_code=None,
        state_version=2,
        created_at=now,
        updated_at=now,
    )
    assert plan.draft is not None
    with pytest.raises(ValidationError, match="ready"):
        DirectorPlan.model_validate({**plan.model_dump(), "draft": None})
    with pytest.raises(ValidationError, match="failed"):
        DirectorPlan.model_validate(
            {
                **plan.model_dump(),
                "status": DirectorPlanStatus.FAILED,
                "draft": None,
                "error_code": None,
                "output_sha256": None,
            }
        )
