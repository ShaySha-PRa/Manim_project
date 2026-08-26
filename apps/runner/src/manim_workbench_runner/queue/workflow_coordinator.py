from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol
from uuid import UUID


class WorkflowCoordinatorOutcome(str, Enum):
    IDLE = "idle"
    SUCCEEDED = "succeeded"
    LEASE_LOST = "lease_lost"
    FAILED = "failed"
    RETRY_SCHEDULED = "retry_scheduled"


@dataclass(frozen=True, slots=True)
class WorkflowTaskLease:
    task_id: UUID
    run_id: UUID
    project_id: UUID
    owner_id: UUID
    kind: str
    lease_token: str
    attempt_count: int
    payload: dict[str, object]


class WorkflowTaskLifecyclePort(Protocol):
    def claim(
        self, kind: str, *, runner_id: str, lease_seconds: int
    ) -> WorkflowTaskLease | None: ...

    def complete(self, task_id: UUID, lease_token: str) -> bool: ...

    def release(self, task_id: UUID, lease_token: str, *, retry_at: datetime) -> bool: ...


@dataclass(frozen=True, slots=True)
class WorkflowTaskExecution:
    retry_at: datetime | None = None


class WorkflowTaskExecutor(Protocol):
    def execute(self, lease: WorkflowTaskLease) -> WorkflowTaskExecution | None: ...


class WorkflowTaskCoordinator:
    """Run one persistent workflow task without treating wake-up delivery as truth."""

    def __init__(
        self,
        lifecycle: WorkflowTaskLifecyclePort,
        executor: WorkflowTaskExecutor,
        *,
        runner_id: str,
        lease_seconds: int = 300,
    ) -> None:
        if not runner_id:
            raise ValueError("runner_id cannot be empty")
        if not 5 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be in the range [5, 3600]")
        self._lifecycle = lifecycle
        self._executor = executor
        self._runner_id = runner_id
        self._lease_seconds = lease_seconds

    def run_once(self, kind: str) -> WorkflowCoordinatorOutcome:
        lease = self._lifecycle.claim(
            kind, runner_id=self._runner_id, lease_seconds=self._lease_seconds
        )
        if lease is None:
            return WorkflowCoordinatorOutcome.IDLE
        try:
            execution = self._executor.execute(lease)
        except Exception:  # noqa: BLE001 - task lease expiry is the recovery boundary
            return WorkflowCoordinatorOutcome.FAILED
        if execution is not None and execution.retry_at is not None:
            if not self._lifecycle.release(
                lease.task_id, lease.lease_token, retry_at=execution.retry_at
            ):
                return WorkflowCoordinatorOutcome.LEASE_LOST
            return WorkflowCoordinatorOutcome.RETRY_SCHEDULED
        if not self._lifecycle.complete(lease.task_id, lease.lease_token):
            return WorkflowCoordinatorOutcome.LEASE_LOST
        return WorkflowCoordinatorOutcome.SUCCEEDED
