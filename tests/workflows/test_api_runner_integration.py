from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from manim_workbench_api.delivery.service import DeliveryNotFound, DeliveryService
from manim_workbench_api.workflows import WorkflowArtifactStore, WorkflowTaskQueue
from manim_workbench_api.workflows.models import SceneRunCreateRequest
from manim_workbench_api.workflows.service import WorkflowService
from manim_workbench_contracts import RenderProfile, SceneBlockRunStatus
from manim_workbench_runner.queue import (
    PersistentWorkflowWorker,
    RedisWorkflowSignalQueue,
    SqliteWorkflowTaskLifecycle,
    WorkflowCoordinatorOutcome,
    WorkflowTaskCoordinator,
)
from sqlalchemy import Engine, text

from tests.workflows.test_repository import OWNER_A, OWNER_B, _workflow_fixture
from tests.workflows.test_workflow_artifacts import _principal
from tests.workflows.test_workflow_task_executor import (
    _complete_segment,
    _executor,
    _TeachingAdapter,
)

pytest_plugins = ("tests.workflows.test_repository",)


class _Clock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


class _LostSignals:
    def blpop(self, keys, timeout):  # type: ignore[no-untyped-def]
        del keys, timeout
        raise OSError("workflow signal lost")


class _FailingNotifier:
    def wake(self, kind, task_id):  # type: ignore[no-untyped-def]
        del kind, task_id
        raise OSError("workflow notifier unavailable")


def _worker(
    engine: Engine,
    teaching: _TeachingAdapter,
    store: WorkflowArtifactStore,
    artifact_root: Path,
    staging_root: Path,
    clock: _Clock,
) -> PersistentWorkflowWorker:
    executor = _executor(
        engine,
        teaching,
        store,
        artifact_root,
        staging_root,
        clock=clock,
    )
    return PersistentWorkflowWorker(
        RedisWorkflowSignalQueue(_LostSignals()),
        WorkflowTaskCoordinator(
            SqliteWorkflowTaskLifecycle(WorkflowTaskQueue(engine), clock=clock),
            executor,
            runner_id="api-runner-integration",
            lease_seconds=30,
        ),
    )


def test_api_submission_runner_recovery_poll_and_authenticated_artifact_download(
    engine: Engine, tmp_path: Path
) -> None:
    repository = WorkflowService(engine).repository
    _, first, _, workflow = _workflow_fixture(repository)
    request = SceneRunCreateRequest(
        workflow_version_id=workflow.id,
        profile=RenderProfile.PREVIEW,
        idempotency_key="api-runner-success",
    )
    api = WorkflowService(engine, _FailingNotifier())
    run = api.submit_scene_run(first.id, OWNER_A, request)
    assert api.submit_scene_run(first.id, OWNER_A, request).id == run.id
    artifact_root = tmp_path / "artifacts"
    staging_root = tmp_path / "staging"
    store = WorkflowArtifactStore(engine, artifact_root, staging_root)
    teaching = _TeachingAdapter()
    base = datetime.now(timezone.utc) + timedelta(seconds=1)
    clock = _Clock(base)

    first_pass = _worker(
        engine, teaching, store, artifact_root, staging_root, clock
    ).run_once(timeout_seconds=0.1)
    assert first_pass is WorkflowCoordinatorOutcome.RETRY_SCHEDULED
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM workflow_tasks WHERE run_id=:run"),
            {"run": str(run.id)},
        ).scalar_one() == 1
        program_run_id = connection.execute(
            text("SELECT id FROM program_render_runs WHERE scene_block_run_id=:run"),
            {"run": str(run.id)},
        ).scalar_one()
    for segment_index in range(2):
        _complete_segment(
            engine,
            artifact_root,
            program_run_id=program_run_id,
            segment_index=segment_index,
        )

    clock.current = base + timedelta(seconds=6)
    outcome = _worker(
        engine, teaching, store, artifact_root, staging_root, clock
    ).run_once(timeout_seconds=0.1)
    assert outcome is WorkflowCoordinatorOutcome.SUCCEEDED
    restarted_api = WorkflowService(engine)
    projected = restarted_api.get_scene_run_for_owner(run.id, OWNER_A)
    assert projected.status is SceneBlockRunStatus.SUCCEEDED
    assert projected.preview_artifact_id is not None
    with engine.connect() as connection:
        events = connection.execute(
            text(
                "SELECT state_version,status FROM scene_block_run_events "
                "WHERE run_id=:run ORDER BY state_version"
            ),
            {"run": str(run.id)},
        ).all()
    assert [row[0] for row in events] == list(range(len(events)))
    assert [row[1] for row in events] == [
        "queued",
        "planning",
        "compiling",
        "rendering",
        "succeeded",
    ]
    opened = DeliveryService(engine, artifact_root).artifact(
        _principal(OWNER_A), projected.preview_artifact_id, attachment=True
    )
    assert opened.path.is_file() and opened.path.stat().st_size > 0
    with pytest.raises(DeliveryNotFound):
        DeliveryService(engine, artifact_root).artifact(
            _principal(OWNER_B), projected.preview_artifact_id, attachment=True
        )
    assert teaching.calls == 1


def test_failed_scene_run_remains_auditable_and_can_be_retried_as_a_new_run(
    engine: Engine, tmp_path: Path
) -> None:
    repository = WorkflowService(engine).repository
    _, first, _, workflow = _workflow_fixture(repository)
    api = WorkflowService(engine, _FailingNotifier())
    failed = api.submit_scene_run(
        first.id,
        OWNER_A,
        SceneRunCreateRequest(
            workflow_version_id=workflow.id,
            profile=RenderProfile.FINAL,
            idempotency_key="api-runner-failure",
        ),
    )
    artifact_root = tmp_path / "artifacts"
    staging_root = tmp_path / "staging"
    store = WorkflowArtifactStore(engine, artifact_root, staging_root)
    teaching = _TeachingAdapter()
    base = datetime.now(timezone.utc) + timedelta(seconds=1)
    clock = _Clock(base)
    assert _worker(
        engine, teaching, store, artifact_root, staging_root, clock
    ).run_once(timeout_seconds=0.1) is WorkflowCoordinatorOutcome.RETRY_SCHEDULED
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE render_jobs SET status='failed',failure_code='render_failed' "
                "WHERE id=(SELECT render_job_id FROM program_render_segments "
                "WHERE segment_index=0 AND program_render_run_id=(SELECT id FROM "
                "program_render_runs WHERE scene_block_run_id=:run))"
            ),
            {"run": str(failed.id)},
        )
    clock.current = base + timedelta(seconds=6)
    assert _worker(
        engine, teaching, store, artifact_root, staging_root, clock
    ).run_once(timeout_seconds=0.1) is WorkflowCoordinatorOutcome.SUCCEEDED
    failed_projection = WorkflowService(engine).get_scene_run_for_owner(failed.id, OWNER_A)
    assert failed_projection.status is SceneBlockRunStatus.FAILED
    assert failed_projection.preview_artifact_id is None
    assert failed_projection.final_artifact_id is None

    retry = api.submit_scene_run(
        first.id,
        OWNER_A,
        SceneRunCreateRequest(
            workflow_version_id=workflow.id,
            profile=RenderProfile.FINAL,
            idempotency_key="api-runner-failure-retry",
        ),
    )
    assert retry.id != failed.id
    assert retry.status is SceneBlockRunStatus.QUEUED
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM scene_block_runs WHERE scene_block_version_id=:block"),
            {"block": str(first.id)},
        ).scalar_one() == 2
        assert connection.execute(
            text("SELECT COUNT(*) FROM workflow_artifacts WHERE scene_block_run_id=:run"),
            {"run": str(failed.id)},
        ).scalar_one() == 0
