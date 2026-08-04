from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from manim_workbench_contracts import (
    RenderArtifactPayload,
    RenderJobCompletion,
    RenderJobFailureCode,
    RenderJobStatus,
    RenderJobSubmission,
    RenderProfile,
)
from sqlalchemy import Engine, text


@dataclass(frozen=True)
class JobRecord:
    id: UUID
    project_id: UUID
    owner_id: UUID
    code_version_id: UUID
    profile: RenderProfile
    status: RenderJobStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    failure_code: str | None
    attempt_count: int
    lease_owner: str | None
    lease_token: str | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    cancellation_requested_at: datetime | None
    state_version: int


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def from_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class JobRepository:
    """All SQL is parameterized and every lifecycle write is version-conditional."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, job_id: UUID) -> JobRecord | None:
        with self._engine.connect() as connection:
            return self._get(connection, job_id)

    def create_or_get(self, submission: RenderJobSubmission) -> tuple[JobRecord, bool]:
        now = utc_now()
        job_id = uuid4()
        with self._engine.begin() as connection:
            inserted = connection.execute(
                text(
                    """
                    INSERT INTO render_jobs (
                        id, project_id, owner_id, code_version_id, profile, status,
                        idempotency_key, created_at, attempt_count, state_version
                    ) VALUES (
                        :id, :project_id, :owner_id, :code_version_id, :profile, :status,
                        :idempotency_key, :created_at, 0, 0
                    ) ON CONFLICT(idempotency_key) DO NOTHING
                    """
                ),
                {
                    "id": str(job_id),
                    "project_id": str(submission.project_id),
                    "owner_id": str(submission.owner_id),
                    "code_version_id": str(submission.code_version_id),
                    "profile": submission.profile.value,
                    "status": RenderJobStatus.QUEUED.value,
                    "idempotency_key": submission.idempotency_key,
                    "created_at": as_timestamp(now),
                },
            )
            if inserted.rowcount == 1:
                record = self._get(connection, job_id)
                assert record is not None
                return record, True
            existing = connection.execute(
                text("SELECT id FROM render_jobs WHERE idempotency_key = :idempotency_key"),
                {"idempotency_key": submission.idempotency_key},
            ).scalar_one()
            record = self._get(connection, UUID(existing))
            assert record is not None
            return record, False

    def claim(self, job_id: UUID, runner_id: str, lease_seconds: int) -> JobRecord | None:
        now = utc_now()
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        token = secrets.token_hex(32)
        with self._engine.begin() as connection:
            current = self._get(connection, job_id)
            if current is None:
                return None
            updated = connection.execute(
                text(
                    """
                    UPDATE render_jobs
                    SET status = :claimed, lease_owner = :lease_owner, lease_token = :lease_token,
                        lease_expires_at = :lease_expires_at, heartbeat_at = :heartbeat_at,
                        attempt_count = attempt_count + 1, state_version = state_version + 1
                    WHERE id = :id AND status = :queued AND attempt_count < 3
                      AND state_version = :state_version
                    """
                ),
                {
                    "claimed": RenderJobStatus.CLAIMED.value,
                    "lease_owner": runner_id,
                    "lease_token": token,
                    "lease_expires_at": as_timestamp(lease_expires_at),
                    "heartbeat_at": as_timestamp(now),
                    "id": str(job_id),
                    "queued": RenderJobStatus.QUEUED.value,
                    "state_version": current.state_version,
                },
            )
            if updated.rowcount != 1:
                return None
            return self._get(connection, job_id)

    def heartbeat(self, job_id: UUID, lease_token: str, extend_seconds: int) -> JobRecord | None:
        now = utc_now()
        expires = now + timedelta(seconds=extend_seconds)
        return self._update_active_lease(
            job_id,
            lease_token,
            """
            SET lease_expires_at = :lease_expires_at, heartbeat_at = :heartbeat_at,
                state_version = state_version + 1
            """,
            {"lease_expires_at": as_timestamp(expires), "heartbeat_at": as_timestamp(now)},
            (RenderJobStatus.CLAIMED, RenderJobStatus.RUNNING),
        )

    def start(self, job_id: UUID, lease_token: str) -> JobRecord | None:
        now = utc_now()
        return self._update_active_lease(
            job_id,
            lease_token,
            """
            SET status = :running, started_at = COALESCE(started_at, :started_at),
                state_version = state_version + 1
            """,
            {"running": RenderJobStatus.RUNNING.value, "started_at": as_timestamp(now)},
            (RenderJobStatus.CLAIMED,),
        )

    def request_cancel(self, job_id: UUID) -> JobRecord | None:
        now = utc_now()
        with self._engine.begin() as connection:
            current = self._get(connection, job_id)
            if current is None:
                return None
            if current.status is RenderJobStatus.QUEUED:
                connection.execute(
                    text(
                        """
                        UPDATE render_jobs
                        SET status = :cancelled, finished_at = :finished_at,
                            state_version = state_version + 1
                        WHERE id = :id AND status = :queued AND state_version = :state_version
                        """
                    ),
                    {
                        "cancelled": RenderJobStatus.CANCELLED.value,
                        "finished_at": as_timestamp(now),
                        "id": str(job_id),
                        "queued": RenderJobStatus.QUEUED.value,
                        "state_version": current.state_version,
                    },
                )
            elif current.status in {RenderJobStatus.CLAIMED, RenderJobStatus.RUNNING} and (
                current.cancellation_requested_at is None
            ):
                connection.execute(
                    text(
                        """
                        UPDATE render_jobs
                        SET cancellation_requested_at = :cancellation_requested_at,
                            state_version = state_version + 1
                        WHERE id = :id AND status IN (:claimed, :running)
                          AND cancellation_requested_at IS NULL AND state_version = :state_version
                        """
                    ),
                    {
                        "cancellation_requested_at": as_timestamp(now),
                        "id": str(job_id),
                        "claimed": RenderJobStatus.CLAIMED.value,
                        "running": RenderJobStatus.RUNNING.value,
                        "state_version": current.state_version,
                    },
                )
            return self._get(connection, job_id)

    def complete(self, job_id: UUID, completion: RenderJobCompletion) -> JobRecord | None:
        now = utc_now()
        with self._engine.begin() as connection:
            current = self._get(connection, job_id)
            if current is None:
                return None
            updated = connection.execute(
                text(
                    """
                    UPDATE render_jobs
                    SET status = :succeeded, finished_at = :finished_at,
                        state_version = state_version + 1
                    WHERE id = :id AND status = :running AND lease_token = :lease_token
                      AND lease_expires_at > :now AND cancellation_requested_at IS NULL
                      AND state_version = :state_version
                    """
                ),
                {
                    "succeeded": RenderJobStatus.SUCCEEDED.value,
                    "finished_at": as_timestamp(now),
                    "id": str(job_id),
                    "running": RenderJobStatus.RUNNING.value,
                    "lease_token": completion.lease_token,
                    "now": as_timestamp(now),
                    "state_version": current.state_version,
                },
            )
            if updated.rowcount != 1:
                return None
            self._insert_artifacts(connection, current, completion.artifacts, now)
            return self._get(connection, job_id)

    def fail(
        self, job_id: UUID, lease_token: str, failure_code: RenderJobFailureCode
    ) -> JobRecord | None:
        now = utc_now()
        return self._update_active_lease(
            job_id,
            lease_token,
            """
            SET status = :failed, failure_code = :failure_code, finished_at = :finished_at,
                state_version = state_version + 1
            """,
            {
                "failed": RenderJobStatus.FAILED.value,
                "failure_code": failure_code.value,
                "finished_at": as_timestamp(now),
            },
            (RenderJobStatus.RUNNING,),
        )

    def _update_active_lease(
        self,
        job_id: UUID,
        lease_token: str,
        assignments: str,
        parameters: dict[str, str],
        statuses: tuple[RenderJobStatus, ...],
    ) -> JobRecord | None:
        now = utc_now()
        status_parameters = {
            f"status_{index}": status.value for index, status in enumerate(statuses)
        }
        status_clause = ", ".join(f":status_{index}" for index in range(len(statuses)))
        with self._engine.begin() as connection:
            current = self._get(connection, job_id)
            if current is None:
                return None
            update_parameters = {
                **parameters,
                **status_parameters,
                "id": str(job_id),
                "lease_token": lease_token,
                "now": as_timestamp(now),
                "state_version": current.state_version,
            }
            updated = connection.execute(
                text(
                    f"""
                    UPDATE render_jobs
                    {assignments}
                    WHERE id = :id AND status IN ({status_clause}) AND lease_token = :lease_token
                      AND lease_expires_at > :now AND cancellation_requested_at IS NULL
                      AND state_version = :state_version
                    """
                ),
                update_parameters,
            )
            if updated.rowcount != 1:
                return None
            return self._get(connection, job_id)

    @staticmethod
    def _insert_artifacts(
        connection: object,
        job: JobRecord,
        artifacts: tuple[RenderArtifactPayload, ...],
        now: datetime,
    ) -> None:
        for artifact in artifacts:
            connection.execute(  # type: ignore[attr-defined]
                text(
                    """
                    INSERT INTO artifacts (
                        id, project_id, owner_id, render_job_id, kind, relative_path,
                        sha256, byte_size, created_at
                    ) VALUES (
                        :id, :project_id, :owner_id, :render_job_id, :kind, :relative_path,
                        :sha256, :byte_size, :created_at
                    )
                    """
                ),
                {
                    "id": str(uuid4()),
                    "project_id": str(job.project_id),
                    "owner_id": str(job.owner_id),
                    "render_job_id": str(job.id),
                    "kind": artifact.kind.value,
                    "relative_path": artifact.relative_path,
                    "sha256": artifact.sha256,
                    "byte_size": artifact.byte_size,
                    "created_at": as_timestamp(now),
                },
            )

    @staticmethod
    def _get(connection: object, job_id: UUID) -> JobRecord | None:
        row = connection.execute(  # type: ignore[attr-defined]
            text("SELECT * FROM render_jobs WHERE id = :id"), {"id": str(job_id)}
        ).mappings().first()
        if row is None:
            return None
        return JobRecord(
            id=UUID(row["id"]),
            project_id=UUID(row["project_id"]),
            owner_id=UUID(row["owner_id"]),
            code_version_id=UUID(row["code_version_id"]),
            profile=RenderProfile(row["profile"]),
            status=RenderJobStatus(row["status"]),
            created_at=from_timestamp(row["created_at"]),  # type: ignore[arg-type]
            started_at=from_timestamp(row["started_at"]),
            finished_at=from_timestamp(row["finished_at"]),
            failure_code=row["failure_code"],
            attempt_count=row["attempt_count"],
            lease_owner=row["lease_owner"],
            lease_token=row["lease_token"],
            lease_expires_at=from_timestamp(row["lease_expires_at"]),
            heartbeat_at=from_timestamp(row["heartbeat_at"]),
            cancellation_requested_at=from_timestamp(row["cancellation_requested_at"]),
            state_version=row["state_version"],
        )
