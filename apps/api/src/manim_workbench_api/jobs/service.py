from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from manim_workbench_contracts import (
    RenderJobCompletion,
    RenderJobFailureReport,
    RenderJobHeartbeat,
    RenderJobLease,
    RenderJobLeaseRequest,
    RenderJobStatus,
    RenderJobSubmission,
)

from .dependencies import JobSignalPublisher
from .errors import (
    ARTIFACT_SET_INVALID,
    CANCELLATION_REQUESTED,
    JOB_NOT_CLAIMABLE,
    JOB_NOT_FOUND,
    LEASE_INVALID,
    STATE_CONFLICT,
)
from .models import JobResponse
from .repository import JobRecord, JobRepository

_REQUIRED_ARTIFACT_KINDS = {"video", "thumbnail", "render_log", "metadata"}


class JobService:
    def __init__(self, repository: JobRepository, publisher: JobSignalPublisher) -> None:
        self._repository = repository
        self._publisher = publisher

    def submit(self, submission: RenderJobSubmission) -> tuple[JobResponse, bool]:
        record, created = self._repository.create_or_get(submission)
        if created:
            try:
                self._publisher.publish(record.id)
            except Exception:
                # Redis is only a lossy wake-up signal; the committed SQLite row is recoverable.
                pass
        return self._response(record), created

    def get(self, job_id: UUID) -> JobResponse:
        return self._response(self._require_job(job_id))

    def cancel(self, job_id: UUID) -> JobResponse:
        record = self._repository.request_cancel(job_id)
        if record is None:
            raise JOB_NOT_FOUND
        return self._response(record)

    def claim(self, job_id: UUID, request: RenderJobLeaseRequest) -> RenderJobLease:
        if self._repository.get(job_id) is None:
            raise JOB_NOT_FOUND
        record = self._repository.claim(job_id, request.runner_id, request.lease_seconds)
        if record is None or record.lease_token is None or record.lease_expires_at is None:
            raise JOB_NOT_CLAIMABLE
        return RenderJobLease(
            job_id=record.id,
            code_version_id=record.code_version_id,
            profile=record.profile,
            lease_token=record.lease_token,
            lease_expires_at=record.lease_expires_at,
            attempt_number=record.attempt_count,
        )

    def heartbeat(self, job_id: UUID, request: RenderJobHeartbeat) -> JobResponse:
        before = self._require_job(job_id)
        record = self._repository.heartbeat(job_id, request.lease_token, request.extend_seconds)
        if record is None:
            self._raise_lease_mutation_error(job_id, before, request.lease_token)
        return self._response(record)

    def start(self, job_id: UUID, request: RenderJobHeartbeat) -> JobResponse:
        before = self._require_job(job_id)
        record = self._repository.start(job_id, request.lease_token)
        if record is None:
            self._raise_lease_mutation_error(job_id, before, request.lease_token)
        return self._response(record)

    def complete(self, job_id: UUID, completion: RenderJobCompletion) -> JobResponse:
        kinds = {artifact.kind.value for artifact in completion.artifacts}
        if kinds != _REQUIRED_ARTIFACT_KINDS or len(kinds) != len(completion.artifacts):
            raise ARTIFACT_SET_INVALID
        before = self._require_job(job_id)
        record = self._repository.complete(job_id, completion)
        if record is None:
            self._raise_lease_mutation_error(job_id, before, completion.lease_token)
        return self._response(record)

    def fail(self, job_id: UUID, report: RenderJobFailureReport) -> JobResponse:
        before = self._require_job(job_id)
        record = self._repository.fail(job_id, report.lease_token, report.failure_code)
        if record is None:
            self._raise_lease_mutation_error(job_id, before, report.lease_token)
        return self._response(record)

    def _require_job(self, job_id: UUID) -> JobRecord:
        record = self._repository.get(job_id)
        if record is None:
            raise JOB_NOT_FOUND
        return record

    def _raise_lease_mutation_error(
        self, job_id: UUID, before: JobRecord, lease_token: str
    ) -> None:
        current = self._repository.get(job_id)
        if current is None:
            raise JOB_NOT_FOUND
        if current.cancellation_requested_at is not None:
            raise CANCELLATION_REQUESTED
        now = datetime.now(timezone.utc)
        if (
            current.lease_token != lease_token
            or current.lease_expires_at is None
            or current.lease_expires_at <= now
        ):
            raise LEASE_INVALID
        if before.status != current.status or current.status in {
            RenderJobStatus.SUCCEEDED,
            RenderJobStatus.FAILED,
            RenderJobStatus.CANCELLED,
        }:
            raise STATE_CONFLICT
        raise STATE_CONFLICT

    @staticmethod
    def _response(record: JobRecord) -> JobResponse:
        return JobResponse(
            id=record.id,
            project_id=record.project_id,
            owner_id=record.owner_id,
            code_version_id=record.code_version_id,
            profile=record.profile,
            status=record.status,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            failure_code=record.failure_code,
            attempt_count=record.attempt_count,
            cancellation_requested_at=record.cancellation_requested_at,
            state_version=record.state_version,
        )
