from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from manim_workbench_api.database import create_database_engine
from manim_workbench_api.workflows.director.repository import (
    DirectorAttempt,
    DirectorPlanNotFound,
    DirectorRepository,
)
from manim_workbench_contracts import (
    DirectorDraft,
    DirectorGlobalBriefDraft,
    DirectorPlanRequest,
    DirectorPlanStatus,
    DirectorSceneDraft,
    Language,
    ScenePipelineMode,
    WorkflowStylePreset,
)
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from tests.workflows.migration_support import upgrade_workflow_database

OWNER_A = UUID("00000000-0000-0000-0000-000000000001")
OWNER_B = UUID("00000000-0000-0000-0000-000000000002")
PROJECT_A = UUID("10000000-0000-0000-0000-000000000001")
PROJECT_B = UUID("10000000-0000-0000-0000-000000000002")
PROJECT_ARCHIVED = UUID("10000000-0000-0000-0000-000000000003")


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    database_path = tmp_path / "director-repository.db"
    config = upgrade_workflow_database(database_path)
    command.upgrade(config, "head")
    result = create_database_engine(f"sqlite:///{database_path}")
    now = "2026-08-31T00:00:00+00:00"
    with result.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id,email,created_at) VALUES (:id,:email,:now)"),
            [
                {"id": str(OWNER_A), "email": "a@test.dev", "now": now},
                {"id": str(OWNER_B), "email": "b@test.dev", "now": now},
            ],
        )
        connection.execute(
            text(
                "INSERT INTO projects (id,owner_id,title,created_at,archived_at) "
                "VALUES (:id,:owner,:title,:now,:archived)"
            ),
            [
                {
                    "id": str(PROJECT_A),
                    "owner": str(OWNER_A),
                    "title": "A",
                    "now": now,
                    "archived": None,
                },
                {
                    "id": str(PROJECT_B),
                    "owner": str(OWNER_B),
                    "title": "B",
                    "now": now,
                    "archived": None,
                },
                {
                    "id": str(PROJECT_ARCHIVED),
                    "owner": str(OWNER_A),
                    "title": "Archived",
                    "now": now,
                    "archived": now,
                },
            ],
        )
    return result


def _request(project_id: UUID = PROJECT_A, *, assets: tuple[UUID, ...] = ()) -> DirectorPlanRequest:
    return DirectorPlanRequest(
        project_id=project_id,
        objective="Create a bounded scientific explanation.",
        language=Language.ZH_CN,
        target_duration_seconds=60,
        style_preset=WorkflowStylePreset.DARK_SCIENTIFIC,
        asset_version_ids=assets,
        idempotency_key="director-repository-request-0001",
    )


def _draft() -> DirectorDraft:
    return DirectorDraft(
        global_brief=DirectorGlobalBriefDraft(
            title="Director plan",
            language=Language.ZH_CN,
            target_duration_seconds=60,
            style_preset=WorkflowStylePreset.DARK_SCIENTIFIC,
            background="#10131a",
            palette=("#4488ff", "#ffcc22"),
        ),
        scenes=(
            DirectorSceneDraft(
                title="Concept",
                prompt="Explain the concept.",
                pipeline_mode=ScenePipelineMode.TEACHING,
                target_duration_seconds=30,
                semantic_summary="Introduce the concept.",
            ),
            DirectorSceneDraft(
                title="Evidence",
                prompt="Show bounded computed evidence.",
                pipeline_mode=ScenePipelineMode.SCIENTIFIC,
                target_duration_seconds=30,
                semantic_summary="Show the evidence.",
            ),
        ),
    )


def test_create_is_idempotent_cache_scoped_and_cross_owner_hidden(engine: Engine) -> None:
    repository = DirectorRepository(engine)
    plan, created = repository.create_or_get(
        _request(),
        owner_id=OWNER_A,
        cache_key="a" * 64,
        input_sha256="b" * 64,
        prompt_template_version="workflow-director-v1",
    )
    replay, replay_created = repository.create_or_get(
        _request(),
        owner_id=OWNER_A,
        cache_key="a" * 64,
        input_sha256="b" * 64,
        prompt_template_version="workflow-director-v1",
    )
    assert created is True
    assert replay_created is False
    assert replay.id == plan.id
    assert replay.status is DirectorPlanStatus.QUEUED
    with pytest.raises(DirectorPlanNotFound):
        repository.get(plan.id, PROJECT_A, OWNER_B)
    with pytest.raises(DirectorPlanNotFound):
        repository.get(plan.id, PROJECT_B, OWNER_A)


def test_create_rejects_archived_project_and_unscoped_asset(engine: Engine) -> None:
    repository = DirectorRepository(engine)
    with pytest.raises(DirectorPlanNotFound):
        repository.create_or_get(
            _request(PROJECT_ARCHIVED),
            owner_id=OWNER_A,
            cache_key="a" * 64,
            input_sha256="b" * 64,
            prompt_template_version="workflow-director-v1",
        )
    with pytest.raises(DirectorPlanNotFound):
        repository.create_or_get(
            _request(assets=(uuid4(),)),
            owner_id=OWNER_A,
            cache_key="c" * 64,
            input_sha256="d" * 64,
            prompt_template_version="workflow-director-v1",
        )


def test_events_enforce_one_state_chain_and_attempts_are_append_only(engine: Engine) -> None:
    repository = DirectorRepository(engine)
    plan, _ = repository.create_or_get(
        _request(),
        owner_id=OWNER_A,
        cache_key="a" * 64,
        input_sha256="b" * 64,
        prompt_template_version="workflow-director-v1",
    )
    planning = repository.transition(
        plan.id,
        PROJECT_A,
        OWNER_A,
        expected_state_version=0,
        status=DirectorPlanStatus.PLANNING,
    )
    assert planning.state_version == 1
    ready = repository.transition(
        plan.id,
        PROJECT_A,
        OWNER_A,
        expected_state_version=1,
        status=DirectorPlanStatus.READY,
        draft=_draft(),
        output_sha256="c" * 64,
        attempt_count=1,
        provider_model="director-test",
    )
    assert ready.state_version == 2
    with pytest.raises(ValueError, match="stale"):
        repository.transition(
            plan.id,
            PROJECT_A,
            OWNER_A,
            expected_state_version=1,
            status=DirectorPlanStatus.FAILED,
            error_code="director_failed",
        )

    attempt = DirectorAttempt(
        id=uuid4(),
        plan_id=plan.id,
        owner_id=OWNER_A,
        attempt_number=1,
        status="succeeded",
        provider_model="director-test",
        provider_request_id="request-1",
        prompt_template_version="workflow-director-v1",
        prompt_sha256="d" * 64,
        prompt_tokens=100,
        completion_tokens=50,
        candidate_sha256="c" * 64,
        diagnostic_sha256=None,
        error_code=None,
        created_at=datetime.now(timezone.utc),
    )
    repository.append_attempt(attempt)
    assert repository.list_attempts(plan.id, OWNER_A) == (attempt,)
    with pytest.raises(IntegrityError, match="append-only"):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE workflow_director_attempts SET status='failed' WHERE id=:id"),
                {"id": str(attempt.id)},
            )


def test_apply_is_atomic_idempotent_and_records_director_provenance(engine: Engine) -> None:
    repository = DirectorRepository(engine)
    plan, _ = repository.create_or_get(
        _request(),
        owner_id=OWNER_A,
        cache_key="a" * 64,
        input_sha256="b" * 64,
        prompt_template_version="workflow-director-v1",
    )
    planning = repository.transition(
        plan.id,
        PROJECT_A,
        OWNER_A,
        expected_state_version=0,
        status=DirectorPlanStatus.PLANNING,
    )
    ready = repository.transition(
        plan.id,
        PROJECT_A,
        OWNER_A,
        expected_state_version=planning.state_version,
        status=DirectorPlanStatus.READY,
        draft=_draft(),
        output_sha256="c" * 64,
        attempt_count=1,
        provider_model="director-test",
    )
    with pytest.raises(DirectorPlanNotFound):
        repository.apply(
            ready.id,
            PROJECT_A,
            OWNER_A,
            draft=_draft(),
            scene_asset_version_ids=((uuid4(),), ()),
            idempotency_key="director-apply-atomic-0001",
        )
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM video_workflows")).scalar_one() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM scene_blocks")).scalar_one() == 0

    applied = repository.apply(
        ready.id,
        PROJECT_A,
        OWNER_A,
        draft=_draft(),
        scene_asset_version_ids=((), ()),
        idempotency_key="director-apply-atomic-0001",
    )
    replay = repository.apply(
        ready.id,
        PROJECT_A,
        OWNER_A,
        draft=_draft(),
        scene_asset_version_ids=((), ()),
        idempotency_key="director-apply-atomic-0001",
    )
    assert replay.id == applied.id
    with engine.connect() as connection:
        provenance = connection.execute(
            text(
                "SELECT director_plan_id,director_edits_json "
                "FROM video_workflow_versions WHERE id=:id"
            ),
            {"id": str(applied.id)},
        ).one()
        assert provenance[0] == str(ready.id)
        assert "director-apply-atomic-0001" in provenance[1]
        assert connection.execute(text("SELECT COUNT(*) FROM scene_block_runs")).scalar_one() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM workflow_tasks")).scalar_one() == 0
