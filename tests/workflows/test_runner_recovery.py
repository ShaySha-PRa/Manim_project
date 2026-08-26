from __future__ import annotations

from datetime import datetime, timedelta, timezone

from manim_workbench_api.workflows import (
    WorkflowRepository,
    WorkflowTaskKind,
    WorkflowTaskQueue,
)
from manim_workbench_contracts import RenderProfile
from manim_workbench_runner.queue import (
    SqliteWorkflowTaskLifecycle,
    WorkflowCoordinatorOutcome,
    WorkflowTaskCoordinator,
    WorkflowTaskExecution,
    WorkflowTaskLease,
)
from sqlalchemy import Engine, text

from tests.workflows.test_repository import (
    OWNER_A,
    PROJECT_A,
    _workflow_fixture,
)

pytest_plugins = ("tests.workflows.test_repository",)


class QueueLifecycle:
    def __init__(self, queue: WorkflowTaskQueue, times: list[datetime]) -> None:
        self.queue = queue
        self.times = iter(times)

    def claim(self, kind: str, *, runner_id: str, lease_seconds: int):  # type: ignore[no-untyped-def]
        task = self.queue.claim(
            WorkflowTaskKind(kind),
            worker_id=runner_id,
            lease_seconds=lease_seconds,
            now=next(self.times),
        )
        if task is None:
            return None
        assert task.lease_token is not None
        return WorkflowTaskLease(
            task_id=task.id,
            run_id=task.run_id,
            project_id=task.project_id,
            owner_id=task.owner_id,
            kind=task.kind.value,
            lease_token=task.lease_token,
            attempt_count=task.attempt_count,
            payload=task.payload,
        )

    def complete(self, task_id, lease_token):  # type: ignore[no-untyped-def]
        return self.queue.complete(task_id, lease_token, now=next(self.times))

    def release(self, task_id, lease_token, *, retry_at):  # type: ignore[no-untyped-def]
        return self.queue.release(
            task_id, lease_token, retry_at=retry_at, now=next(self.times)
        )


class CrashOnceIdempotentExecutor:
    def __init__(self) -> None:
        self.calls = 0
        self.published_keys: set[str] = set()

    def execute(self, lease: WorkflowTaskLease) -> None:
        self.calls += 1
        key = str(lease.payload["cache_key"])
        self.published_keys.add(key)
        if self.calls == 1:
            raise RuntimeError("crash after atomic publish before terminal commit")


def test_production_sqlite_lifecycle_preserves_scoped_identity_and_releases_short_lease(
    engine: Engine,
) -> None:
    repository = WorkflowRepository(engine)
    _, _, _, workflow_version = _workflow_fixture(repository)
    run = repository.create_composition_run(
        workflow_version_id=workflow_version.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        profile=RenderProfile.PREVIEW,
        cache_key="7" * 64,
        idempotency_key="production-lifecycle",
    )
    base = datetime(2026, 8, 23, 9, 0, tzinfo=timezone.utc)
    queue = WorkflowTaskQueue(engine)
    queue.submit(
        kind=WorkflowTaskKind.COMPOSITION,
        run_id=run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        idempotency_key="production-lifecycle",
        payload={"profile": "preview"},
        now=base,
    )
    clock_values = iter((base, base + timedelta(seconds=1)))
    lifecycle = SqliteWorkflowTaskLifecycle(queue, clock=lambda: next(clock_values))
    lease = lifecycle.claim("composition", runner_id="runner", lease_seconds=30)
    assert lease is not None
    assert lease.project_id == PROJECT_A
    assert lease.owner_id == OWNER_A
    assert lifecycle.release(
        lease.task_id,
        lease.lease_token,
        retry_at=base + timedelta(seconds=10),
    )
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT status,lease_token,available_at FROM workflow_tasks WHERE id=:id"
            ),
            {"id": str(lease.task_id)},
        ).one()
    assert row[0] == "queued"
    assert row[1] is None
    assert datetime.fromisoformat(row[2]) == base + timedelta(seconds=10)


def test_runner_reclaims_after_publish_crash_without_duplicate_artifact_set(
    engine: Engine,
) -> None:
    repository = WorkflowRepository(engine)
    _, _, _, workflow_version = _workflow_fixture(repository)
    run = repository.create_composition_run(
        workflow_version_id=workflow_version.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        profile=RenderProfile.FINAL,
        cache_key="9" * 64,
        idempotency_key="runner-recovery",
    )
    base = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)
    queue = WorkflowTaskQueue(engine)
    queue.submit(
        kind=WorkflowTaskKind.COMPOSITION,
        run_id=run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        idempotency_key="runner-recovery",
        payload={"cache_key": "9" * 64},
        now=base,
    )
    lifecycle = QueueLifecycle(
        queue,
        [
            base,
            base + timedelta(seconds=31),
            base + timedelta(seconds=32),
        ],
    )
    executor = CrashOnceIdempotentExecutor()
    coordinator = WorkflowTaskCoordinator(
        lifecycle, executor, runner_id="runner-recovery", lease_seconds=30
    )
    assert coordinator.run_once("composition") is WorkflowCoordinatorOutcome.FAILED
    assert coordinator.run_once("composition") is WorkflowCoordinatorOutcome.SUCCEEDED
    assert executor.calls == 2
    assert executor.published_keys == {"9" * 64}


def test_active_segment_releases_lease_until_bounded_retry(engine: Engine) -> None:
    repository = WorkflowRepository(engine)
    _, _, _, workflow_version = _workflow_fixture(repository)
    run = repository.create_composition_run(
        workflow_version_id=workflow_version.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        profile=RenderProfile.PREVIEW,
        cache_key="8" * 64,
        idempotency_key="runner-bounded-retry",
    )
    base = datetime(2026, 8, 23, 11, 0, tzinfo=timezone.utc)
    queue = WorkflowTaskQueue(engine)
    queue.submit(
        kind=WorkflowTaskKind.COMPOSITION,
        run_id=run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        idempotency_key="runner-bounded-retry",
        payload={"cache_key": "8" * 64},
        now=base,
    )
    lifecycle = QueueLifecycle(
        queue,
        [base, base + timedelta(seconds=1), base + timedelta(seconds=5),
         base + timedelta(seconds=11), base + timedelta(seconds=12)],
    )

    class WaitOnce:
        calls = 0

        def execute(self, lease):  # type: ignore[no-untyped-def]
            del lease
            self.calls += 1
            if self.calls == 1:
                return WorkflowTaskExecution(retry_at=base + timedelta(seconds=10))
            return None

    executor = WaitOnce()
    coordinator = WorkflowTaskCoordinator(
        lifecycle, executor, runner_id="runner-retry", lease_seconds=30
    )
    assert coordinator.run_once("composition") is WorkflowCoordinatorOutcome.RETRY_SCHEDULED
    assert coordinator.run_once("composition") is WorkflowCoordinatorOutcome.IDLE
    assert coordinator.run_once("composition") is WorkflowCoordinatorOutcome.SUCCEEDED
    assert executor.calls == 2
