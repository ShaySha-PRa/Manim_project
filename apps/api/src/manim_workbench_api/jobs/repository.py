from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from manim_workbench_contracts import (
    RenderArtifactPayload,
    RenderJobCompletion,
    RenderJobFailureCode,
    RenderJobStatus,
    RenderJobSubmission,
    RenderProfile,
)
from sqlalchemy import Connection, Engine, text


@dataclass(frozen=True)
class JobRecord:
    id: UUID
    project_id: UUID
    owner_id: UUID
    code_version_id: UUID | None
    program_render_segment_id: UUID | None
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
    concat_group_id: UUID | None
    segment_index: int | None


@dataclass(frozen=True)
class WorkItem:
    scene_class: str
    source_code: str
    source_sha256: str
    content_plan_version_id: UUID | None
    target_duration_seconds: float


@dataclass(frozen=True)
class ClaimResult:
    record: JobRecord | None
    work_item: WorkItem | None
    work_item_invalid: bool = False


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
            typed_sources = self._has_typed_sources(connection)
            if not typed_sources and submission.program_render_segment_id is not None:
                raise ValueError("ProgramRenderSegment jobs require migration 0009")
            if submission.program_render_segment_id is not None:
                self._validate_program_source_submission(connection, submission)
            if typed_sources:
                insert_statement = text(
                    """
                    INSERT INTO render_jobs (
                        id, project_id, owner_id, code_version_id,
                        program_render_segment_id, profile, status, idempotency_key,
                        created_at, attempt_count, state_version, concat_group_id, segment_index
                    ) VALUES (
                        :id, :project_id, :owner_id, :code_version_id,
                        :program_render_segment_id, :profile, :status, :idempotency_key,
                        :created_at, 0, 0, :concat_group_id, :segment_index
                    ) ON CONFLICT(idempotency_key) DO NOTHING
                    """
                )
            else:
                insert_statement = text(
                    """
                    INSERT INTO render_jobs (
                        id, project_id, owner_id, code_version_id, profile, status,
                        idempotency_key, created_at, attempt_count, state_version,
                        concat_group_id, segment_index
                    ) VALUES (
                        :id, :project_id, :owner_id, :code_version_id, :profile, :status,
                        :idempotency_key, :created_at, 0, 0, :concat_group_id, :segment_index
                    ) ON CONFLICT(idempotency_key) DO NOTHING
                    """
                )
            inserted = connection.execute(
                insert_statement,
                {
                    "id": str(job_id),
                    "project_id": str(submission.project_id),
                    "owner_id": str(submission.owner_id),
                    "code_version_id": (
                        str(submission.code_version_id) if submission.code_version_id else None
                    ),
                    "program_render_segment_id": (
                        str(submission.program_render_segment_id)
                        if submission.program_render_segment_id
                        else None
                    ),
                    "profile": submission.profile.value,
                    "status": RenderJobStatus.QUEUED.value,
                    "idempotency_key": submission.idempotency_key,
                    "created_at": as_timestamp(now),
                    "concat_group_id": (
                        str(submission.concat_group_id) if submission.concat_group_id else None
                    ),
                    "segment_index": submission.segment_index,
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

    @staticmethod
    def _has_typed_sources(connection: Connection) -> bool:
        return any(
            row[1] == "program_render_segment_id"
            for row in connection.exec_driver_sql("PRAGMA table_info(render_jobs)")
        )

    @staticmethod
    def _validate_program_source_submission(
        connection: Connection, submission: RenderJobSubmission
    ) -> None:
        if not JobRepository._has_program_render_segments(connection):
            raise ValueError("ProgramRenderSegment jobs require migration 0010")
        row = (
            connection.execute(
                text(
                    "SELECT segments.scene_class,segments.source_code,"
                    "segments.source_sha256,NULL AS content_plan_version_id,"
                    "segments.target_duration_seconds "
                    "FROM program_render_segments AS segments "
                    "JOIN program_render_runs AS runs "
                    "ON runs.id=segments.program_render_run_id "
                    "WHERE segments.id=:segment AND runs.project_id=:project "
                    "AND runs.owner_id=:owner AND segments.segment_index=:index"
                ),
                {
                    "segment": str(submission.program_render_segment_id),
                    "project": str(submission.project_id),
                    "owner": str(submission.owner_id),
                    "index": submission.segment_index,
                },
            )
            .mappings()
            .one_or_none()
        )
        if JobRepository._validated_work_item(row) is None:
            raise ValueError("ProgramRenderSegment source identity is invalid")

    def claim(self, job_id: UUID, runner_id: str, lease_seconds: int) -> ClaimResult:
        now = utc_now()
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        token = secrets.token_hex(32)
        with self._engine.begin() as connection:
            current = self._get(connection, job_id)
            if current is None:
                return ClaimResult(None, None)
            work_item = self._load_work_item(connection, job_id)
            if work_item is None:
                return ClaimResult(None, None, work_item_invalid=True)
            updated = connection.execute(
                text(
                    """
                    UPDATE render_jobs
                    SET status = :claimed, lease_owner = :lease_owner, lease_token = :lease_token,
                        lease_expires_at = :lease_expires_at, heartbeat_at = :heartbeat_at,
                        attempt_count = attempt_count + 1, state_version = state_version + 1
                    WHERE id = :id AND status = :queued AND attempt_count < 3
                      AND cancellation_requested_at IS NULL
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
                return ClaimResult(None, None)
            record = self._get(connection, job_id)
            assert record is not None
            return ClaimResult(record, work_item)

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
                            lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                            heartbeat_at = NULL,
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
                        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                        heartbeat_at = NULL,
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
                lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                heartbeat_at = NULL,
                state_version = state_version + 1
            """,
            {
                "failed": RenderJobStatus.FAILED.value,
                "failure_code": failure_code.value,
                "finished_at": as_timestamp(now),
            },
            (RenderJobStatus.RUNNING,),
        )

    def confirm_cancelled(self, job_id: UUID, lease_token: str) -> JobRecord | None:
        now = utc_now()
        with self._engine.begin() as connection:
            current = self._get(connection, job_id)
            if current is None:
                return None
            updated = connection.execute(
                text(
                    """
                    UPDATE render_jobs
                    SET status = :cancelled, finished_at = :finished_at,
                        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                        heartbeat_at = NULL, state_version = state_version + 1
                    WHERE id = :id AND status IN (:claimed, :running) AND lease_token = :lease_token
                      AND lease_expires_at > :now AND cancellation_requested_at IS NOT NULL
                      AND state_version = :state_version
                    """
                ),
                {
                    "cancelled": RenderJobStatus.CANCELLED.value,
                    "finished_at": as_timestamp(now),
                    "id": str(job_id),
                    "claimed": RenderJobStatus.CLAIMED.value,
                    "running": RenderJobStatus.RUNNING.value,
                    "lease_token": lease_token,
                    "now": as_timestamp(now),
                    "state_version": current.state_version,
                },
            )
            if updated.rowcount != 1:
                return None
            return self._get(connection, job_id)

    def recoverable(self, limit: int) -> tuple[JobRecord, ...]:
        now = utc_now()
        with self._engine.begin() as connection:
            expired_rows = connection.execute(
                text(
                    """
                    SELECT id FROM render_jobs
                    WHERE status IN (:claimed, :running) AND lease_expires_at <= :now
                    ORDER BY lease_expires_at ASC LIMIT :limit
                    """
                ),
                {
                    "claimed": RenderJobStatus.CLAIMED.value,
                    "running": RenderJobStatus.RUNNING.value,
                    "now": as_timestamp(now),
                    "limit": limit,
                },
            ).scalars()
            for raw_job_id in expired_rows:
                job_id = UUID(raw_job_id)
                current = self._get(connection, job_id)
                if current is None:
                    continue
                if current.cancellation_requested_at is not None:
                    assignments = """
                        SET status = :cancelled, finished_at = :finished_at,
                            lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                            heartbeat_at = NULL, state_version = state_version + 1
                    """
                    parameters = {
                        "cancelled": RenderJobStatus.CANCELLED.value,
                        "finished_at": as_timestamp(now),
                    }
                elif current.attempt_count >= 3:
                    assignments = """
                        SET status = :failed, failure_code = :failure_code,
                            finished_at = :finished_at,
                            lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                            heartbeat_at = NULL, state_version = state_version + 1
                    """
                    parameters = {
                        "failed": RenderJobStatus.FAILED.value,
                        "failure_code": "runner_lost",
                        "finished_at": as_timestamp(now),
                    }
                else:
                    assignments = """
                        SET status = :queued, lease_owner = NULL, lease_token = NULL,
                            lease_expires_at = NULL, heartbeat_at = NULL,
                            state_version = state_version + 1
                    """
                    parameters = {"queued": RenderJobStatus.QUEUED.value}
                connection.execute(
                    text(
                        f"""
                        UPDATE render_jobs
                        {assignments}
                        WHERE id = :id AND status IN (:claimed, :running)
                          AND lease_expires_at <= :now AND state_version = :state_version
                        """
                    ),
                    {
                        **parameters,
                        "id": str(job_id),
                        "claimed": RenderJobStatus.CLAIMED.value,
                        "running": RenderJobStatus.RUNNING.value,
                        "now": as_timestamp(now),
                        "state_version": current.state_version,
                    },
                )
            queued_ids = connection.execute(
                text(
                    """
                    SELECT id FROM render_jobs WHERE status = :queued
                    ORDER BY created_at ASC LIMIT :limit
                    """
                ),
                {"queued": RenderJobStatus.QUEUED.value, "limit": limit},
            ).scalars()
            records = [self._get(connection, UUID(raw_job_id)) for raw_job_id in queued_ids]
            return tuple(record for record in records if record is not None)

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
        connection: Connection,
        job: JobRecord,
        artifacts: tuple[RenderArtifactPayload, ...],
        now: datetime,
    ) -> None:
        for artifact in artifacts:
            connection.execute(
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
    def _load_work_item(connection: Connection, job_id: UUID) -> WorkItem | None:
        typed_sources = JobRepository._has_typed_sources(connection)
        source_columns = (
            "project_id,owner_id,code_version_id,program_render_segment_id,segment_index"
            if typed_sources
            else "project_id,owner_id,code_version_id,NULL AS program_render_segment_id,"
            "segment_index"
        )
        job = (
            connection.execute(
                text(f"SELECT {source_columns} FROM render_jobs WHERE id=:id"),
                {"id": str(job_id)},
            )
            .mappings()
            .one_or_none()
        )
        if job is None:
            return None
        if job["program_render_segment_id"] is not None:
            if not JobRepository._has_program_render_segments(connection):
                return None
            row = (
                connection.execute(
                    text(
                        """
                        SELECT segments.scene_class, segments.source_code,
                               segments.source_sha256, NULL AS content_plan_version_id,
                               segments.target_duration_seconds
                        FROM render_jobs AS jobs
                        JOIN program_render_segments AS segments
                          ON segments.id = jobs.program_render_segment_id
                         AND segments.render_job_id = jobs.id
                         AND segments.segment_index = jobs.segment_index
                        JOIN program_render_runs AS runs
                          ON runs.id = segments.program_render_run_id
                         AND runs.project_id = jobs.project_id
                         AND runs.owner_id = jobs.owner_id
                        WHERE jobs.id = :id
                          AND jobs.code_version_id IS NULL
                          AND jobs.project_id = :project_id
                          AND jobs.owner_id = :owner_id
                          AND segments.segment_index >= 0
                          AND segments.segment_index < runs.segment_count
                          AND (SELECT COUNT(*) FROM program_render_segments AS ordered
                               WHERE ordered.program_render_run_id = runs.id)
                              = runs.segment_count
                          AND (SELECT MIN(ordered.segment_index)
                               FROM program_render_segments AS ordered
                               WHERE ordered.program_render_run_id = runs.id) = 0
                          AND (SELECT MAX(ordered.segment_index)
                               FROM program_render_segments AS ordered
                               WHERE ordered.program_render_run_id = runs.id)
                              = runs.segment_count - 1
                        """
                    ),
                    {
                        "id": str(job_id),
                        "project_id": job["project_id"],
                        "owner_id": job["owner_id"],
                    },
                )
                .mappings()
                .first()
            )
            return JobRepository._validated_work_item(row)
        if job["code_version_id"] is None:
            return None
        has_content_plans = connection.execute(
            text(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'content_plan_versions'"
            )
        ).scalar_one_or_none()
        if has_content_plans is None:
            statement = text(
                """
                SELECT scene_class, source_code, source_sha256,
                       id AS content_plan_version_id, 90 AS target_duration_seconds
                FROM code_versions
                WHERE id = (SELECT code_version_id FROM render_jobs WHERE id = :id)
                """
            )
        else:
            statement = text(
                """
                SELECT code_versions.scene_class, code_versions.source_code,
                       code_versions.source_sha256, code_versions.content_plan_version_id,
                       COALESCE(json_extract(content_plan_versions.content_json,
                                             '$.target_duration_seconds'), 90)
                         AS target_duration_seconds
                FROM render_jobs
                JOIN code_versions ON code_versions.id = render_jobs.code_version_id
                JOIN content_plan_versions
                  ON content_plan_versions.id = code_versions.content_plan_version_id
                WHERE render_jobs.id = :id
                  AND code_versions.project_id = render_jobs.project_id
                  AND code_versions.owner_id = render_jobs.owner_id
                """
            )
        row = (
            connection.execute(
                statement,
                {"id": str(job_id)},
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return JobRepository._validated_work_item(row)

    @staticmethod
    def _has_program_render_segments(connection: Connection) -> bool:
        return (
            connection.execute(
                text(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='program_render_segments'"
                )
            ).scalar_one_or_none()
            is not None
        )

    @staticmethod
    def _validated_work_item(row) -> WorkItem | None:  # type: ignore[no-untyped-def]
        if row is None:
            return None
        scene_class = row["scene_class"]
        source_code = row["source_code"]
        source_sha256 = row["source_sha256"]
        content_plan_version_id = row["content_plan_version_id"]
        target_duration_seconds = row["target_duration_seconds"]
        if (
            not isinstance(scene_class, str)
            or re.fullmatch(r"[A-Z][A-Za-z0-9]{1,99}", scene_class) is None
        ):
            return None
        if not isinstance(source_code, str) or not 1 <= len(source_code) <= 200_000:
            return None
        if (
            not isinstance(source_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
        ):
            return None
        if sha256(source_code.encode("utf-8")).hexdigest() != source_sha256:
            return None
        try:
            plan_id = (
                UUID(str(content_plan_version_id))
                if content_plan_version_id is not None
                else None
            )
            target = float(target_duration_seconds)
        except (TypeError, ValueError):
            return None
        if not 0 < target <= 600:
            return None
        return WorkItem(scene_class, source_code, source_sha256, plan_id, target)

    @staticmethod
    def _get(connection: Connection, job_id: UUID) -> JobRecord | None:
        row = (
            connection.execute(
                text("SELECT * FROM render_jobs WHERE id = :id"), {"id": str(job_id)}
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return JobRecord(
            id=UUID(row["id"]),
            project_id=UUID(row["project_id"]),
            owner_id=UUID(row["owner_id"]),
            code_version_id=(
                UUID(str(row["code_version_id"])) if row["code_version_id"] else None
            ),
            program_render_segment_id=(
                UUID(str(row["program_render_segment_id"]))
                if row.get("program_render_segment_id")
                else None
            ),
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
            concat_group_id=(
                UUID(str(row["concat_group_id"])) if row["concat_group_id"] else None
            ),
            segment_index=(int(row["segment_index"]) if row["segment_index"] is not None else None),
        )
