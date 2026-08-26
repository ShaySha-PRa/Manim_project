from __future__ import annotations

from uuid import uuid4

from manim_workbench_api.workflows import (
    WorkflowRepository,
    WorkflowTaskKind,
    WorkflowTaskQueue,
)
from manim_workbench_api.workflows.models import SceneRunCreateRequest
from manim_workbench_api.workflows.runtime import RedisWorkflowTaskNotifier
from manim_workbench_api.workflows.service import WorkflowService
from manim_workbench_api.workflows.signals import WORKFLOW_SIGNAL_KEYS
from manim_workbench_contracts import RenderProfile
from manim_workbench_runner.queue import (
    PersistentWorkflowWorker,
    RedisWorkflowSignalQueue,
    SqliteWorkflowTaskLifecycle,
    WorkflowCoordinatorOutcome,
    WorkflowTaskCoordinator,
)
from sqlalchemy import Engine, text

from tests.workflows.test_repository import OWNER_A, PROJECT_A, _workflow_fixture

pytest_plugins = ("tests.workflows.test_repository",)


class _RecordingRedis:
    def __init__(self) -> None:
        self.pushed: list[tuple[str, bytes]] = []

    def rpush(self, key: str, payload: bytes) -> int:
        self.pushed.append((key, payload))
        return len(self.pushed)


def test_api_notifier_uses_independent_content_free_workflow_channels(
    engine: Engine,
) -> None:
    repository = WorkflowRepository(engine)
    _, first, _, workflow = _workflow_fixture(repository)
    scene_run = repository.create_scene_block_run(
        scene_block_version_id=first.id,
        workflow_version_id=workflow.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        cache_key="a" * 64,
        idempotency_key="signal-scene-run",
    )
    composition_run = repository.create_composition_run(
        workflow_version_id=workflow.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        profile=RenderProfile.PREVIEW,
        cache_key="b" * 64,
        idempotency_key="signal-composition-run",
    )
    redis = _RecordingRedis()
    queue = WorkflowTaskQueue(engine, RedisWorkflowTaskNotifier(redis))
    first_task = queue.submit(
        kind=WorkflowTaskKind.SCENE_PROGRAM,
        run_id=scene_run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        idempotency_key="signal-scene-task",
        payload={"private_prompt": "must stay in SQLite"},
    )
    second_task = queue.submit(
        kind=WorkflowTaskKind.COMPOSITION,
        run_id=composition_run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        idempotency_key="signal-composition-task",
        payload={"artifact_ids": [str(uuid4())]},
    )
    assert redis.pushed == [
        (
            WORKFLOW_SIGNAL_KEYS[WorkflowTaskKind.SCENE_PROGRAM.value],
            str(first_task.id).encode("ascii"),
        ),
        (
            WORKFLOW_SIGNAL_KEYS[WorkflowTaskKind.COMPOSITION.value],
            str(second_task.id).encode("ascii"),
        ),
    ]
    assert all(b"private_prompt" not in payload for _, payload in redis.pushed)


class _CaptureNotifier:
    def __init__(self) -> None:
        self.task_ids = []

    def wake(self, kind, task_id):  # type: ignore[no-untyped-def]
        self.task_ids.append((kind, task_id))


def test_api_scene_submission_returns_after_durable_enqueue_without_running_generation(
    engine: Engine,
) -> None:
    repository = WorkflowRepository(engine)
    _, first, _, workflow = _workflow_fixture(repository)
    notifier = _CaptureNotifier()
    service = WorkflowService(engine, notifier)
    request = SceneRunCreateRequest(
        workflow_version_id=workflow.id,
        profile=RenderProfile.PREVIEW,
        idempotency_key="async-api-scene-submission",
    )
    submitted = service.submit_scene_run(first.id, OWNER_A, request)
    duplicate = service.submit_scene_run(first.id, OWNER_A, request)
    assert duplicate.id == submitted.id
    assert submitted.status.value == "queued"
    assert len(notifier.task_ids) == 1
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM workflow_tasks WHERE run_id=:run"),
            {"run": str(submitted.id)},
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT COUNT(*) FROM program_render_runs WHERE scene_block_run_id=:run"),
            {"run": str(submitted.id)},
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT COUNT(*) FROM render_jobs")
        ).scalar_one() == 0


class _UnavailableRedis:
    def blpop(self, keys, timeout):  # type: ignore[no-untyped-def]
        del keys, timeout
        raise OSError("redis is down")


class _CaptureExecutor:
    def __init__(self) -> None:
        self.run_ids = []

    def execute(self, lease):  # type: ignore[no-untyped-def]
        self.run_ids.append(lease.run_id)
        return None


def test_runner_scans_sqlite_when_workflow_redis_signal_is_lost(engine: Engine) -> None:
    repository = WorkflowRepository(engine)
    _, _, _, workflow = _workflow_fixture(repository)
    run = repository.create_composition_run(
        workflow_version_id=workflow.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        profile=RenderProfile.FINAL,
        cache_key="c" * 64,
        idempotency_key="lost-signal-composition-run",
    )
    queue = WorkflowTaskQueue(engine)
    task = queue.submit(
        kind=WorkflowTaskKind.COMPOSITION,
        run_id=run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        idempotency_key="lost-signal-composition-task",
        payload={"profile": "final"},
    )
    executor = _CaptureExecutor()
    worker = PersistentWorkflowWorker(
        RedisWorkflowSignalQueue(_UnavailableRedis()),
        WorkflowTaskCoordinator(
            SqliteWorkflowTaskLifecycle(queue),
            executor,
            runner_id="lost-signal-runner",
            lease_seconds=30,
        ),
    )
    assert worker.run_once(timeout_seconds=0.1) is WorkflowCoordinatorOutcome.SUCCEEDED
    assert executor.run_ids == [run.id]
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT status FROM workflow_tasks WHERE id=:id"),
            {"id": str(task.id)},
        ).scalar_one() == "complete"
