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

from .dependencies import JobSignalPublisher, JobSignalUnavailable
from .errors import (
    ARTIFACT_SET_INVALID,
    CANCELLATION_REQUESTED,
    IDENTITY_CONFLICT,
    JOB_NOT_CLAIMABLE,
    JOB_NOT_FOUND,
    LEASE_INVALID,
    STATE_CONFLICT,
    WORK_ITEM_INVALID,
)
from .models import JobResponse, RecoverableJobsResponse
from .repository import JobRecord, JobRepository

_REQUIRED_ARTIFACT_KINDS = {"video", "thumbnail", "render_log", "metadata"}


class JobService:
    def __init__(self, repository: JobRepository, publisher: JobSignalPublisher) -> None:
        self._repository = repository
        self._publisher = publisher

    def submit(self, submission: RenderJobSubmission) -> tuple[JobResponse, bool]:
        record, created = self._repository.create_or_get(submission)
        if not created and (
            record.project_id != submission.project_id
            or record.owner_id != submission.owner_id
            or record.code_version_id != submission.code_version_id
            or record.program_render_segment_id != submission.program_render_segment_id
            or record.profile != submission.profile
            or record.concat_group_id != submission.concat_group_id
            or record.segment_index != submission.segment_index
        ):
            raise IDENTITY_CONFLICT
        if created:
            try:
                self._publisher.publish(record.id)
            except JobSignalUnavailable:
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
        claim = self._repository.claim(job_id, request.runner_id, request.lease_seconds)
        if claim.work_item_invalid:
            raise WORK_ITEM_INVALID
        record = claim.record
        if record is None or record.lease_token is None or record.lease_expires_at is None:
            raise JOB_NOT_CLAIMABLE
        assert claim.work_item is not None
        return RenderJobLease(
            job_id=record.id,
            code_version_id=record.code_version_id,
            program_render_segment_id=record.program_render_segment_id,
            content_plan_version_id=claim.work_item.content_plan_version_id,
            target_duration_seconds=claim.work_item.target_duration_seconds,
            profile=record.profile,
            scene_class=claim.work_item.scene_class,
            source_code=claim.work_item.source_code,
            source_sha256=claim.work_item.source_sha256,
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

    def confirm_cancelled(self, job_id: UUID, lease_token: str) -> JobResponse:
        before = self._require_job(job_id)
        record = self._repository.confirm_cancelled(job_id, lease_token)
        if record is None:
            self._raise_cancel_confirmation_error(job_id, before, lease_token)
        return self._response(record)

    def recoverable(self, limit: int) -> RecoverableJobsResponse:
        records = self._repository.recoverable(limit)
        return RecoverableJobsResponse(jobs=tuple(self._response(record) for record in records))

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

    def _raise_cancel_confirmation_error(
        self, job_id: UUID, before: JobRecord, lease_token: str
    ) -> None:
        current = self._repository.get(job_id)
        if current is None:
            raise JOB_NOT_FOUND
        if current.lease_token != lease_token or current.lease_expires_at is None:
            raise LEASE_INVALID
        if current.cancellation_requested_at is None:
            raise STATE_CONFLICT
        if before.status != current.status:
            raise STATE_CONFLICT
        raise STATE_CONFLICT

    @staticmethod
    def _response(record: JobRecord) -> JobResponse:
        return JobResponse(
            id=record.id,
            project_id=record.project_id,
            owner_id=record.owner_id,
            code_version_id=record.code_version_id,
            program_render_segment_id=record.program_render_segment_id,
            profile=record.profile,
            status=record.status,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            failure_code=record.failure_code,
            attempt_count=record.attempt_count,
            cancellation_requested_at=record.cancellation_requested_at,
            state_version=record.state_version,
            concat_group_id=record.concat_group_id,
            segment_index=record.segment_index,
        )
