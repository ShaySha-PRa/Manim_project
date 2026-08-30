from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from manim_workbench_api.workflows import WorkflowTaskKind, WorkflowTaskQueue
from manim_workbench_api.workflows.director.repository import DirectorRepository
from manim_workbench_api.workflows.director.service import DirectorPlanningService
from manim_workbench_contracts import DirectorPlanStatus
from sqlalchemy import Engine

from tests.workflows.test_director_repository import OWNER_A, PROJECT_A
from tests.workflows.test_director_service import (
    FakeProvider,
    _candidate,
    _request,
)
from tests.workflows.test_director_service import (
    director_engine as _director_engine_fixture,
)


class FailingNotifier:
    def wake(self, _kind, _task_id) -> None:  # type: ignore[no-untyped-def]
        raise OSError("Redis unavailable")


@pytest.fixture
def director_engine(tmp_path: Path) -> Engine:
    return _director_engine_fixture.__wrapped__(tmp_path)


def test_director_task_survives_signal_loss_and_expired_lease_without_duplicate_provider(
    director_engine: Engine,
) -> None:
    provider = FakeProvider(_candidate())
    service = DirectorPlanningService(DirectorRepository(director_engine), provider)
    plan, _ = service.create(_request(), OWNER_A)
    queue = WorkflowTaskQueue(director_engine, FailingNotifier())
    now = datetime.now(timezone.utc)
    task = queue.submit(
        kind=WorkflowTaskKind.DIRECTOR_PLAN,
        run_id=plan.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        idempotency_key="director-task-idempotency-0001",
        payload={"director_plan_id": str(plan.id)},
        now=now,
    )
    first = queue.claim(
        WorkflowTaskKind.DIRECTOR_PLAN,
        worker_id="lost-runner",
        lease_seconds=5,
        now=now,
    )
    assert first is not None and first.attempt_count == 1
    recovered = queue.claim(
        WorkflowTaskKind.DIRECTOR_PLAN,
        worker_id="recovered-runner",
        lease_seconds=60,
        now=now + timedelta(seconds=6),
    )
    assert recovered is not None and recovered.id == task.id
    assert recovered.attempt_count == 2

    ready = service.execute(plan.id, PROJECT_A, OWNER_A)
    assert ready.status is DirectorPlanStatus.READY
    assert recovered.lease_token is not None
    assert queue.complete(
        recovered.id,
        recovered.lease_token,
        now=now + timedelta(seconds=7),
    )
    assert (
        queue.claim(
            WorkflowTaskKind.DIRECTOR_PLAN,
            worker_id="extra-runner",
            lease_seconds=60,
            now=now + timedelta(seconds=8),
        )
        is None
    )
    assert service.execute(plan.id, PROJECT_A, OWNER_A) == ready
    assert provider.calls == 1
