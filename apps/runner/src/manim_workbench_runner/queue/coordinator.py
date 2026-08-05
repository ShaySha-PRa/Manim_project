"""Duplicate-safe Runner coordination over API and sandbox ports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from time import sleep as default_sleep
from uuid import UUID

from manim_workbench_contracts import RenderJobLease

from .redis_queue import SignalQueueUnavailable
from .signals import JobSignalDecodeError
from .types import (
    JobControl,
    JobLifecyclePort,
    LeaseNotActiveError,
    SandboxCancellationRequested,
    SandboxExecutionError,
    SandboxExecutor,
    SandboxWorkItem,
    SignalQueue,
)


class CoordinatorOutcome(str, Enum):
    IDLE = "idle"
    QUEUE_UNAVAILABLE = "queue_unavailable"
    MALFORMED_SIGNAL = "malformed_signal"
    CLAIM_REJECTED = "claim_rejected"
    LEASE_LOST = "lease_lost"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class QueueRetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.1
    max_delay_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if self.base_delay_seconds <= 0 or self.max_delay_seconds <= 0:
            raise ValueError("retry delays must be positive")
        if self.base_delay_seconds > self.max_delay_seconds:
            raise ValueError("base retry delay cannot exceed max retry delay")

    def delay_after(self, failed_attempt: int) -> float:
        return min(self.base_delay_seconds * (2 ** (failed_attempt - 1)), self.max_delay_seconds)


@dataclass(frozen=True)
class RecoveryOutcome:
    signaled_job_ids: tuple[UUID, ...]
    failed_job_ids: tuple[UUID, ...]


class RunnerCoordinator:
    """Coordinates each wake-up without accessing SQLite or Docker directly.

    A duplicate signal is harmless because the API's atomic claim returns ``None`` for
    a job that is no longer queued.  A stale lease must be reported by the lifecycle
    port as ``LeaseNotActiveError`` or ``JobControl(active=False, ...)``; in both cases
    this coordinator never starts or completes a sandbox attempt.
    """

    def __init__(
        self,
        *,
        queue: SignalQueue,
        lifecycle: JobLifecyclePort,
        sandbox: SandboxExecutor,
        runner_id: str,
        retry_policy: QueueRetryPolicy | None = None,
        sleep: Callable[[float], None] = default_sleep,
        lease_seconds: int = 300,
        heartbeat_extend_seconds: int = 300,
    ) -> None:
        if not runner_id:
            raise ValueError("runner_id cannot be empty")
        if not 5 <= lease_seconds <= 300:
            raise ValueError("lease_seconds must be within the API contract range")
        if not 5 <= heartbeat_extend_seconds <= 300:
            raise ValueError("heartbeat_extend_seconds must be within the API contract range")
        self._queue = queue
        self._lifecycle = lifecycle
        self._sandbox = sandbox
        self._runner_id = runner_id
        self._retry_policy = retry_policy or QueueRetryPolicy()
        self._sleep = sleep
        self._lease_seconds = lease_seconds
        self._heartbeat_extend_seconds = heartbeat_extend_seconds

    def run_once(self, *, timeout_seconds: float) -> CoordinatorOutcome:
        """Process at most one signal and acknowledge every decoded signal exactly once."""
        try:
            signal = self._queue.claim(timeout_seconds=timeout_seconds)
        except SignalQueueUnavailable:
            return CoordinatorOutcome.QUEUE_UNAVAILABLE
        except JobSignalDecodeError:
            return CoordinatorOutcome.MALFORMED_SIGNAL
        if signal is None:
            self.recover()
            return CoordinatorOutcome.IDLE

        try:
            return self._handle_signal(signal.job_id)
        finally:
            self._queue.ack(signal)

    def recover(self) -> RecoveryOutcome:
        """Re-signal durable queued or expired jobs without treating Redis as state."""
        signaled: list[UUID] = []
        failed: list[UUID] = []
        for job_id in self._lifecycle.list_recoverable_job_ids():
            if self._enqueue_with_backoff(job_id):
                signaled.append(job_id)
            else:
                failed.append(job_id)
        return RecoveryOutcome(signaled_job_ids=tuple(signaled), failed_job_ids=tuple(failed))

    def _handle_signal(self, job_id: UUID) -> CoordinatorOutcome:
        try:
            lease = self._lifecycle.claim(
                job_id, runner_id=self._runner_id, lease_seconds=self._lease_seconds
            )
            if lease is None:
                return CoordinatorOutcome.CLAIM_REJECTED

            start_control = self._lifecycle.start(lease)
            cancellation_outcome = self._control_outcome(
                lease,
                start_control,
                active_work=None,
            )
            if cancellation_outcome is not None:
                return cancellation_outcome

            pre_execution_control = self._lifecycle.heartbeat(
                lease,
                extend_seconds=self._heartbeat_extend_seconds,
            )
            cancellation_outcome = self._control_outcome(
                lease,
                pre_execution_control,
                active_work=None,
            )
            if cancellation_outcome is not None:
                return cancellation_outcome

            work = SandboxWorkItem(lease=lease)
            try:
                result = self._sandbox.execute(
                    work,
                    control_probe=lambda: self._poll_running_control(work),
                )
            except SandboxCancellationRequested:
                self._lifecycle.confirm_cancelled(lease)
                return CoordinatorOutcome.CANCELLED

            final_heartbeat = self._lifecycle.heartbeat(
                lease, extend_seconds=self._heartbeat_extend_seconds
            )
            cancellation_outcome = self._control_outcome(
                lease,
                final_heartbeat,
                active_work=work,
            )
            if cancellation_outcome is not None:
                return cancellation_outcome

            completion_control = self._lifecycle.complete(lease, result.artifacts)
            cancellation_outcome = self._control_outcome(
                lease,
                completion_control,
                active_work=work,
            )
            if cancellation_outcome is not None:
                return cancellation_outcome
            return CoordinatorOutcome.SUCCEEDED
        except LeaseNotActiveError:
            return CoordinatorOutcome.LEASE_LOST
        except SandboxExecutionError as error:
            self._lifecycle.fail(lease, error.failure_code)
            return CoordinatorOutcome.FAILED

    def _poll_running_control(self, work: SandboxWorkItem) -> JobControl:
        control = self._lifecycle.heartbeat(
            work.lease,
            extend_seconds=self._heartbeat_extend_seconds,
        )
        if not control.active:
            self._sandbox.cancel(work)
            raise LeaseNotActiveError("lease expired or was superseded while running")
        if control.cancellation_requested:
            self._sandbox.cancel(work)
            raise SandboxCancellationRequested("job cancellation requested while running")
        return control

    def _control_outcome(
        self,
        lease: RenderJobLease,
        control: JobControl,
        *,
        active_work: SandboxWorkItem | None,
    ) -> CoordinatorOutcome | None:
        if not control.active:
            return CoordinatorOutcome.LEASE_LOST
        if control.cancellation_requested:
            if active_work is not None:
                self._sandbox.cancel(active_work)
            self._lifecycle.confirm_cancelled(lease)
            return CoordinatorOutcome.CANCELLED
        return None

    def _enqueue_with_backoff(self, job_id: UUID) -> bool:
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            try:
                self._queue.enqueue(job_id)
                return True
            except SignalQueueUnavailable:
                if attempt == self._retry_policy.max_attempts:
                    return False
                self._sleep(self._retry_policy.delay_after(attempt))
        raise AssertionError("bounded queue retry loop must return")
