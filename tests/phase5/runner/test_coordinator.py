from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from manim_workbench_contracts import (
    RenderArtifactPayload,
    RenderJobLease,
    RenderProfile,
)
from manim_workbench_runner.queue.coordinator import (
    CoordinatorOutcome,
    QueueRetryPolicy,
    RunnerCoordinator,
)
from manim_workbench_runner.queue.redis_queue import SignalQueueUnavailable
from manim_workbench_runner.queue.types import (
    ClaimedSignal,
    JobControl,
    SandboxControlProbe,
    SandboxExecutionResult,
    SandboxWorkItem,
)


@dataclass
class FakeQueue:
    signals: deque[ClaimedSignal]
    unavailable_enqueues: int = 0

    def __post_init__(self) -> None:
        self.enqueued: list[UUID] = []
        self.acked: list[ClaimedSignal] = []

    def enqueue(self, job_id: UUID) -> None:
        if self.unavailable_enqueues:
            self.unavailable_enqueues -= 1
            raise SignalQueueUnavailable("offline")
        self.enqueued.append(job_id)

    def claim(self, *, timeout_seconds: float) -> ClaimedSignal | None:
        return self.signals.popleft() if self.signals else None

    def ack(self, claim: ClaimedSignal) -> None:
        self.acked.append(claim)


class FakeLifecycle:
    def __init__(self, leases: dict[UUID, RenderJobLease | None]) -> None:
        self.leases = leases
        self.claimed: list[UUID] = []
        self.claim_lease_seconds: list[int] = []
        self.started: list[UUID] = []
        self.heartbeats: list[UUID] = []
        self.heartbeat_extend_seconds: list[int] = []
        self.cancelled: list[UUID] = []
        self.completed: list[tuple[UUID, tuple[RenderArtifactPayload, ...]]] = []
        self.failed: list[UUID] = []
        self.recoverable: tuple[UUID, ...] = ()
        self.next_start = JobControl(active=True, cancellation_requested=False)
        self.next_complete = JobControl(active=True, cancellation_requested=False)
        self.heartbeat_controls: deque[JobControl] = deque()

    def claim(self, job_id: UUID, *, runner_id: str, lease_seconds: int) -> RenderJobLease | None:
        self.claimed.append(job_id)
        self.claim_lease_seconds.append(lease_seconds)
        return self.leases[job_id]

    def start(self, lease: RenderJobLease) -> JobControl:
        self.started.append(lease.job_id)
        return self.next_start

    def heartbeat(self, lease: RenderJobLease, *, extend_seconds: int) -> JobControl:
        self.heartbeats.append(lease.job_id)
        self.heartbeat_extend_seconds.append(extend_seconds)
        if self.heartbeat_controls:
            return self.heartbeat_controls.popleft()
        return JobControl(active=True, cancellation_requested=False)

    def confirm_cancelled(self, lease: RenderJobLease) -> None:
        self.cancelled.append(lease.job_id)

    def complete(
        self,
        lease: RenderJobLease,
        artifacts: tuple[RenderArtifactPayload, ...],
    ) -> JobControl:
        self.completed.append((lease.job_id, artifacts))
        return self.next_complete

    def fail(self, lease: RenderJobLease, failure_code: object) -> None:
        self.failed.append(lease.job_id)

    def list_recoverable_job_ids(self) -> tuple[UUID, ...]:
        return self.recoverable


class FakeSandbox:
    def __init__(self) -> None:
        self.executed: list[SandboxWorkItem] = []
        self.cancelled: list[SandboxWorkItem] = []
        self.poll_during_execute = True

    def execute(
        self,
        work: SandboxWorkItem,
        *,
        control_probe: SandboxControlProbe,
    ) -> SandboxExecutionResult:
        self.executed.append(work)
        if self.poll_during_execute:
            control_probe()
        return SandboxExecutionResult(artifacts=artifacts_for(work.lease.job_id))

    def cancel(self, work: SandboxWorkItem) -> None:
        self.cancelled.append(work)


def lease_for(job_id: UUID) -> RenderJobLease:
    source_code = "from manim import Scene\n\nclass GeneratedScene(Scene):\n    pass\n"
    return RenderJobLease(
        job_id=job_id,
        code_version_id=uuid4(),
        content_plan_version_id=uuid4(),
        target_duration_seconds=10,
        profile=RenderProfile.PREVIEW,
        scene_class="GeneratedScene",
        source_code=source_code,
        source_sha256=sha256(source_code.encode("utf-8")).hexdigest(),
        lease_token="a" * 64,
        lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        attempt_number=1,
    )


def artifacts_for(job_id: UUID) -> tuple[RenderArtifactPayload, ...]:
    digest = sha256(str(job_id).encode("ascii")).hexdigest()
    return (
        RenderArtifactPayload(
            kind="video",
            relative_path="video.mp4",
            sha256=digest,
            byte_size=1,
        ),
        RenderArtifactPayload(
            kind="thumbnail",
            relative_path="thumbnail.jpg",
            sha256=digest,
            byte_size=1,
        ),
        RenderArtifactPayload(
            kind="render_log",
            relative_path="render.log",
            sha256=digest,
            byte_size=1,
        ),
        RenderArtifactPayload(
            kind="metadata",
            relative_path="metadata.json",
            sha256=digest,
            byte_size=1,
        ),
    )


def signal_for(job_id: UUID) -> ClaimedSignal:
    return ClaimedSignal(job_id=job_id)


def coordinator(
    queue: FakeQueue,
    lifecycle: FakeLifecycle,
    sandbox: FakeSandbox,
    *,
    sleeps: list[float] | None = None,
) -> RunnerCoordinator:
    return RunnerCoordinator(
        queue=queue,
        lifecycle=lifecycle,
        sandbox=sandbox,
        runner_id="runner-01",
        retry_policy=QueueRetryPolicy(
            max_attempts=3,
            base_delay_seconds=0.1,
            max_delay_seconds=0.2,
        ),
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
    )


def test_duplicate_signals_create_only_one_effective_lease_and_ack_both() -> None:
    job_id = uuid4()
    queue = FakeQueue(deque([signal_for(job_id), signal_for(job_id)]))
    lifecycle = FakeLifecycle({job_id: lease_for(job_id)})
    sandbox = FakeSandbox()
    runner = coordinator(queue, lifecycle, sandbox)

    assert runner.run_once(timeout_seconds=0.1) is CoordinatorOutcome.SUCCEEDED
    lifecycle.leases[job_id] = None

    assert runner.run_once(timeout_seconds=0.1) is CoordinatorOutcome.CLAIM_REJECTED
    assert [work.lease.job_id for work in sandbox.executed] == [job_id]
    assert sandbox.executed[0].lease.source_code.startswith("from manim import Scene")
    assert (
        sandbox.executed[0].lease.source_sha256
        == sha256(sandbox.executed[0].lease.source_code.encode("utf-8")).hexdigest()
    )
    assert lifecycle.completed == [(job_id, artifacts_for(job_id))]
    assert queue.acked == [signal_for(job_id), signal_for(job_id)]


def test_default_lease_tolerates_short_host_clock_resynchronization() -> None:
    job_id = uuid4()
    queue = FakeQueue(deque([signal_for(job_id)]))
    lifecycle = FakeLifecycle({job_id: lease_for(job_id)})

    outcome = coordinator(queue, lifecycle, FakeSandbox()).run_once(timeout_seconds=0.1)

    assert outcome is CoordinatorOutcome.SUCCEEDED
    assert lifecycle.claim_lease_seconds == [300]
    assert lifecycle.heartbeat_extend_seconds == [300, 300, 300]


def test_quality_rejected_completion_is_reported_as_failed_not_succeeded() -> None:
    job_id = uuid4()
    queue = FakeQueue(deque([signal_for(job_id)]))
    lifecycle = FakeLifecycle({job_id: lease_for(job_id)})
    lifecycle.next_complete = JobControl(
        active=True,
        cancellation_requested=False,
        terminal_failed=True,
    )

    outcome = coordinator(queue, lifecycle, FakeSandbox()).run_once(timeout_seconds=0.1)

    assert outcome is CoordinatorOutcome.FAILED
    assert lifecycle.completed == [(job_id, artifacts_for(job_id))]


def test_claim_rejection_is_acked_without_starting_sandbox() -> None:
    job_id = uuid4()
    queue = FakeQueue(deque([signal_for(job_id)]))
    lifecycle = FakeLifecycle({job_id: None})
    sandbox = FakeSandbox()

    assert (
        coordinator(queue, lifecycle, sandbox).run_once(timeout_seconds=0.1)
        is CoordinatorOutcome.CLAIM_REJECTED
    )
    assert sandbox.executed == []
    assert queue.acked == [signal_for(job_id)]


def test_idle_poll_recovers_durable_jobs_created_or_expired_after_startup() -> None:
    job_id = uuid4()
    queue = FakeQueue(deque())
    lifecycle = FakeLifecycle({})
    lifecycle.recoverable = (job_id,)
    sandbox = FakeSandbox()

    outcome = coordinator(queue, lifecycle, sandbox).run_once(timeout_seconds=0.1)

    assert outcome is CoordinatorOutcome.IDLE
    assert queue.enqueued == [job_id]


def test_cancel_before_start_confirms_cancellation_without_executing_sandbox() -> None:
    job_id = uuid4()
    queue = FakeQueue(deque([signal_for(job_id)]))
    lifecycle = FakeLifecycle({job_id: lease_for(job_id)})
    lifecycle.next_start = JobControl(active=True, cancellation_requested=True)
    sandbox = FakeSandbox()

    assert (
        coordinator(queue, lifecycle, sandbox).run_once(timeout_seconds=0.1)
        is CoordinatorOutcome.CANCELLED
    )
    assert sandbox.executed == []
    assert lifecycle.cancelled == [job_id]
    assert queue.acked == [signal_for(job_id)]


def test_lost_or_old_lease_stops_before_sandbox_and_does_not_complete() -> None:
    job_id = uuid4()
    queue = FakeQueue(deque([signal_for(job_id)]))
    lifecycle = FakeLifecycle({job_id: lease_for(job_id)})
    lifecycle.heartbeat_controls.append(JobControl(active=False, cancellation_requested=False))
    sandbox = FakeSandbox()

    assert (
        coordinator(queue, lifecycle, sandbox).run_once(timeout_seconds=0.1)
        is CoordinatorOutcome.LEASE_LOST
    )
    assert sandbox.executed == []
    assert lifecycle.completed == []
    assert queue.acked == [signal_for(job_id)]


def test_long_running_sandbox_poll_cancels_during_execute_and_never_completes() -> None:
    job_id = uuid4()
    queue = FakeQueue(deque([signal_for(job_id)]))
    lease = lease_for(job_id)
    lifecycle = FakeLifecycle({job_id: lease})
    lifecycle.heartbeat_controls.append(JobControl(active=True, cancellation_requested=False))
    lifecycle.heartbeat_controls.append(JobControl(active=True, cancellation_requested=True))
    sandbox = FakeSandbox()

    outcome = coordinator(queue, lifecycle, sandbox).run_once(timeout_seconds=0.1)

    assert outcome is CoordinatorOutcome.CANCELLED
    assert sandbox.executed == [SandboxWorkItem(lease=lease)]
    assert sandbox.cancelled == [SandboxWorkItem(lease=lease)]
    assert lifecycle.heartbeats == [job_id, job_id]
    assert lifecycle.cancelled == [job_id]
    assert lifecycle.completed == []
    assert queue.acked == [signal_for(job_id)]


def test_sandbox_success_is_closed_to_the_four_required_artifacts() -> None:
    with pytest.raises(ValueError):
        SandboxExecutionResult(artifacts=())


def test_recovery_resignals_queued_and_expired_jobs_with_bounded_backoff() -> None:
    first, second = uuid4(), uuid4()
    queue = FakeQueue(deque(), unavailable_enqueues=2)
    lifecycle = FakeLifecycle({})
    lifecycle.recoverable = (first, second)
    sandbox = FakeSandbox()
    sleeps: list[float] = []

    outcome = coordinator(queue, lifecycle, sandbox, sleeps=sleeps).recover()

    assert outcome.signaled_job_ids == (first, second)
    assert outcome.failed_job_ids == ()
    assert queue.enqueued == [first, second]
    assert sleeps == [0.1, 0.2]


def test_recovery_gives_up_after_bounded_redis_retries_without_crashing_runner() -> None:
    job_id = uuid4()
    queue = FakeQueue(deque(), unavailable_enqueues=3)
    lifecycle = FakeLifecycle({})
    lifecycle.recoverable = (job_id,)
    sandbox = FakeSandbox()
    sleeps: list[float] = []

    outcome = coordinator(queue, lifecycle, sandbox, sleeps=sleeps).recover()

    assert outcome.signaled_job_ids == ()
    assert outcome.failed_job_ids == (job_id,)
    assert sleeps == [0.1, 0.2]
