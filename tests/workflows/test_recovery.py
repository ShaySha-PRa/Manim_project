from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from manim_workbench_api.workflows import (
    WORKFLOW_VERSION_CONFLICT,
    WorkflowRepository,
    WorkflowTaskKind,
    WorkflowTaskQueue,
)
from manim_workbench_contracts import CompositionRunStatus, RenderProfile
from sqlalchemy import Engine, text

from tests.workflows.test_repository import (
    OWNER_A,
    PROJECT_A,
    _workflow_fixture,
)

pytest_plugins = ("tests.workflows.test_repository",)


class FailingNotifier:
    def wake(self, _kind, _task_id):  # type: ignore[no-untyped-def]
        raise OSError("redis unavailable")


def test_sqlite_task_survives_notifier_failure_and_reclaims_expired_lease(
    engine: Engine,
) -> None:
    repository = WorkflowRepository(engine)
    _, _, _, workflow_version = _workflow_fixture(repository)
    run = repository.create_composition_run(
        workflow_version_id=workflow_version.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        profile=RenderProfile.PREVIEW,
        cache_key="e" * 64,
        idempotency_key="composition-recovery",
    )
    queue = WorkflowTaskQueue(engine, FailingNotifier())
    now = datetime(2026, 8, 23, 8, 0, tzinfo=timezone.utc)
    task = queue.submit(
        kind=WorkflowTaskKind.COMPOSITION,
        run_id=run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        idempotency_key="composition-recovery",
        payload={"workflow_version_id": str(workflow_version.id)},
        now=now,
    )
    duplicate = queue.submit(
        kind=WorkflowTaskKind.COMPOSITION,
        run_id=run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        idempotency_key="composition-recovery",
        payload={"workflow_version_id": str(workflow_version.id)},
        now=now,
    )
    assert duplicate.id == task.id

    first = queue.claim(
        WorkflowTaskKind.COMPOSITION, worker_id="runner-1", lease_seconds=30, now=now
    )
    assert first is not None and first.attempt_count == 1 and first.lease_token
    assert (
        queue.claim(
            WorkflowTaskKind.COMPOSITION,
            worker_id="runner-2",
            lease_seconds=30,
            now=now + timedelta(seconds=10),
        )
        is None
    )
    second = queue.claim(
        WorkflowTaskKind.COMPOSITION,
        worker_id="runner-2",
        lease_seconds=30,
        now=now + timedelta(seconds=31),
    )
    assert second is not None and second.attempt_count == 2 and second.lease_token
    assert second.lease_token != first.lease_token
    assert not queue.complete(
        task.id, first.lease_token, now=now + timedelta(seconds=32)
    )
    assert queue.complete(
        task.id, second.lease_token, now=now + timedelta(seconds=32)
    )
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM workflow_tasks")).scalar_one() == 1
        assert connection.execute(
            text("SELECT status FROM workflow_tasks WHERE id=:id"), {"id": str(task.id)}
        ).scalar_one() == "complete"


def test_recovered_composition_has_one_terminal_event_and_stale_worker_loses(
    engine: Engine,
) -> None:
    repository = WorkflowRepository(engine)
    _, _, _, workflow_version = _workflow_fixture(repository)
    run = repository.create_composition_run(
        workflow_version_id=workflow_version.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        profile=RenderProfile.FINAL,
        cache_key="f" * 64,
        idempotency_key="composition-terminal",
    )
    composing = repository.append_composition_run_event(
        run_id=run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        expected_state_version=0,
        status=CompositionRunStatus.COMPOSING,
    )
    assert composing.state_version == 1
    terminal = repository.append_composition_run_event(
        run_id=run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        expected_state_version=1,
        status=CompositionRunStatus.FAILED,
        error_code="runner_recovered_failure",
    )
    assert terminal.state_version == 2
    with pytest.raises(type(WORKFLOW_VERSION_CONFLICT)):
        repository.append_composition_run_event(
            run_id=run.id,
            project_id=PROJECT_A,
            owner_id=OWNER_A,
            expected_state_version=1,
            status=CompositionRunStatus.FAILED,
            error_code="stale_runner_failure",
        )
    with engine.connect() as connection:
        terminal_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM workflow_composition_run_events "
                "WHERE run_id=:run_id AND status IN ('succeeded','failed','not_ready_to_compose')"
            ),
            {"run_id": str(run.id)},
        ).scalar_one()
    assert terminal_count == 1
