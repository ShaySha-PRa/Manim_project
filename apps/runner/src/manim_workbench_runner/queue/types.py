"""Ports and value objects at the Runner-to-API and Runner-to-sandbox boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from manim_workbench_contracts import (
    RenderArtifactPayload,
    RenderJobFailureCode,
    RenderJobLease,
)


@dataclass(frozen=True)
class ClaimedSignal:
    """A destructive queue read awaiting acknowledgement by the coordinator."""

    job_id: UUID


@dataclass(frozen=True)
class JobControl:
    """The only control information a lifecycle call may return to the Runner."""

    active: bool
    cancellation_requested: bool


@dataclass(frozen=True)
class SandboxWorkItem:
    """One immutable lease plus the source/work payload embedded in that lease."""

    lease: RenderJobLease


@dataclass(frozen=True)
class SandboxExecutionResult:
    """The only successful sandbox result accepted by the coordinator."""

    artifacts: tuple[RenderArtifactPayload, ...]

    def __post_init__(self) -> None:
        if type(self.artifacts) is not tuple:
            raise TypeError("sandbox artifacts must be a tuple")
        required_kinds = {"video", "thumbnail", "render_log", "metadata"}
        actual_kinds = {artifact.kind.value for artifact in self.artifacts}
        if len(self.artifacts) != 4 or actual_kinds != required_kinds:
            raise ValueError("sandbox success requires exactly the four standard artifacts")


class SandboxControlProbe(Protocol):
    """Called repeatedly by a running sandbox adapter to renew and inspect its lease."""

    def __call__(self) -> JobControl: ...


class SignalQueue(Protocol):
    """A lossy wake-up queue; durable job state belongs to the API/SQLite."""

    def enqueue(self, job_id: UUID) -> None: ...

    def claim(self, *, timeout_seconds: float) -> ClaimedSignal | None: ...

    def ack(self, claim: ClaimedSignal) -> None: ...


class JobLifecyclePort(Protocol):
    """Runner-facing API port; implementations must never expose SQLite to the Runner."""

    def claim(
        self, job_id: UUID, *, runner_id: str, lease_seconds: int
    ) -> RenderJobLease | None: ...

    def start(self, lease: RenderJobLease) -> JobControl: ...

    def heartbeat(self, lease: RenderJobLease, *, extend_seconds: int) -> JobControl: ...

    def confirm_cancelled(self, lease: RenderJobLease) -> None: ...

    def complete(
        self,
        lease: RenderJobLease,
        artifacts: tuple[RenderArtifactPayload, ...],
    ) -> JobControl: ...

    def fail(self, lease: RenderJobLease, failure_code: RenderJobFailureCode) -> None: ...

    def list_recoverable_job_ids(self) -> tuple[UUID, ...]: ...


class SandboxExecutor(Protocol):
    """Port for Agent C's sandbox implementation; this module never builds Docker commands."""

    def execute(
        self,
        work: SandboxWorkItem,
        *,
        control_probe: SandboxControlProbe,
    ) -> SandboxExecutionResult: ...

    def cancel(self, work: SandboxWorkItem) -> None: ...


class LeaseNotActiveError(RuntimeError):
    """The API rejected an operation because a lease expired or was superseded."""


class LifecycleUnavailable(RuntimeError):
    """The Runner could not reach its private lifecycle API temporarily."""


class SandboxCancellationRequested(RuntimeError):
    """A control probe stopped sandbox execution after observing cancellation."""


class SandboxExecutionError(RuntimeError):
    """A classified sandbox failure that can safely be persisted by the lifecycle API."""

    def __init__(self, failure_code: RenderJobFailureCode) -> None:
        self.failure_code = failure_code
        super().__init__(failure_code.value)
