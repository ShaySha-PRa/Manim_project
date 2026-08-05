from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from manim_workbench_contracts import (
    QualityDiagnostic,
    QualityHumanRatingRequest,
    QualityReport,
    QualityStatus,
)
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from .models import QualityRatingRecord


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


class AppendOutcome(str, Enum):
    CREATED = "created"
    PROVENANCE_INVALID = "provenance_invalid"
    CONFLICT = "conflict"


class QualityReportRepository:
    """Parameterized persistence for immutable Phase 9 quality records."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @property
    def engine(self) -> Engine:
        return self._engine

    def append(
        self,
        report: QualityReport,
        diagnostics: tuple[QualityDiagnostic, ...],
    ) -> AppendOutcome:
        """Atomically insert a report when its entire persisted lineage still matches."""
        try:
            with self._engine.begin() as connection:
                if not self._lineage_matches(connection, report):
                    return AppendOutcome.PROVENANCE_INVALID
                duplicate = connection.execute(
                    text(
                        "SELECT 1 FROM quality_reports WHERE render_job_id = :render_job_id "
                        "AND diagnostic_signature = :diagnostic_signature"
                    ),
                    {
                        "render_job_id": str(report.render_job_id),
                        "diagnostic_signature": report.diagnostic_signature,
                    },
                ).one_or_none()
                if duplicate is not None:
                    return AppendOutcome.CONFLICT
                connection.execute(
                    text(
                        "INSERT INTO quality_reports ("
                        "id, project_id, owner_id, render_job_id, code_version_id, "
                        "content_plan_version_id, status, target_duration_seconds, "
                        "estimated_duration_seconds, actual_duration_seconds, frame_rate, "
                        "frame_count, score, repair_count, diagnostic_signature, provider_model, "
                        "prompt_template_version, content_plan_schema_version, manim_version, "
                        "image_digest, ast_policy_version, diagnostic_policy_version, created_at"
                        ") VALUES ("
                        ":id, :project_id, :owner_id, :render_job_id, :code_version_id, "
                        ":content_plan_version_id, :status, :target_duration_seconds, "
                        ":estimated_duration_seconds, :actual_duration_seconds, :frame_rate, "
                        ":frame_count, :score, :repair_count, :diagnostic_signature, "
                        ":provider_model, "
                        ":prompt_template_version, :content_plan_schema_version, :manim_version, "
                        ":image_digest, :ast_policy_version, :diagnostic_policy_version, "
                        ":created_at"
                        ")"
                    ),
                    self._report_values(report),
                )
                for diagnostic in diagnostics:
                    connection.execute(
                        text(
                            "INSERT INTO quality_diagnostics ("
                            "id, quality_report_id, owner_id, code, severity, stage, message, "
                            "suggestion, evidence_ref, measured_value, threshold_value, created_at"
                            ") VALUES ("
                            ":id, :quality_report_id, :owner_id, :code, :severity, :stage, "
                            ":message, :suggestion, :evidence_ref, :measured_value, "
                            ":threshold_value, :created_at"
                            ")"
                        ),
                        {
                            "id": str(uuid4()),
                            "quality_report_id": str(report.id),
                            "owner_id": str(report.owner_id),
                            "code": diagnostic.code.value,
                            "severity": diagnostic.severity.value,
                            "stage": diagnostic.stage.value,
                            "message": diagnostic.message,
                            "suggestion": diagnostic.suggestion,
                            "evidence_ref": diagnostic.evidence_ref,
                            "measured_value": diagnostic.measured_value,
                            "threshold_value": diagnostic.threshold_value,
                            "created_at": report.created_at.isoformat(),
                        },
                    )
        except IntegrityError:
            return AppendOutcome.CONFLICT
        return AppendOutcome.CREATED

    def get(self, report_id: UUID, owner_id: UUID) -> QualityReport | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM quality_reports WHERE id = :id AND owner_id = :owner_id"),
                    {"id": str(report_id), "owner_id": str(owner_id)},
                )
                .mappings()
                .one_or_none()
            )
        return self._report_from_row(row) if row is not None else None

    def latest_by_job(self, render_job_id: UUID, owner_id: UUID) -> QualityReport | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT * FROM quality_reports WHERE render_job_id = :render_job_id "
                        "AND owner_id = :owner_id ORDER BY created_at DESC, id DESC LIMIT 1"
                    ),
                    {"render_job_id": str(render_job_id), "owner_id": str(owner_id)},
                )
                .mappings()
                .one_or_none()
            )
        return self._report_from_row(row) if row is not None else None

    def list_by_project(
        self,
        project_id: UUID,
        owner_id: UUID,
        cursor: UUID | None,
        limit: int,
    ) -> tuple[tuple[QualityReport, ...], UUID | None] | None:
        with self._engine.connect() as connection:
            if not self._project_owned(connection, project_id, owner_id):
                return None
            cursor_row = self._cursor_row(connection, cursor, project_id, owner_id)
            if cursor is not None and cursor_row is None:
                return None
            rows = (
                connection.execute(
                    text(
                        "SELECT * FROM quality_reports WHERE project_id = :project_id "
                        "AND owner_id = :owner_id AND ("
                        ":cursor_created_at IS NULL OR created_at < :cursor_created_at "
                        "OR (created_at = :cursor_created_at AND id < :cursor_id)"
                        ") ORDER BY created_at DESC, id DESC LIMIT :fetch_limit"
                    ),
                    {
                        "project_id": str(project_id),
                        "owner_id": str(owner_id),
                        "cursor_created_at": cursor_row["created_at"] if cursor_row else None,
                        "cursor_id": cursor_row["id"] if cursor_row else None,
                        "fetch_limit": limit + 1,
                    },
                )
                .mappings()
                .all()
            )
        page_rows = rows[:limit]
        records = tuple(self._report_from_row(row) for row in page_rows)
        next_cursor = records[-1].id if len(rows) > limit and records else None
        return records, next_cursor

    def diagnostics(self, report_id: UUID, owner_id: UUID) -> tuple[QualityDiagnostic, ...] | None:
        with self._engine.connect() as connection:
            if self._get_row(connection, report_id, owner_id) is None:
                return None
            rows = (
                connection.execute(
                    text(
                        "SELECT code, severity, stage, message, suggestion, evidence_ref, "
                        "measured_value, threshold_value FROM quality_diagnostics "
                        "WHERE quality_report_id = :report_id AND owner_id = :owner_id "
                        "ORDER BY id ASC"
                    ),
                    {"report_id": str(report_id), "owner_id": str(owner_id)},
                )
                .mappings()
                .all()
            )
        return tuple(
            QualityDiagnostic(
                code=str(row["code"]),
                severity=str(row["severity"]),
                stage=str(row["stage"]),
                message=str(row["message"]),
                suggestion=str(row["suggestion"]),
                evidence_ref=str(row["evidence_ref"]) if row["evidence_ref"] else None,
                measured_value=float(row["measured_value"])
                if row["measured_value"] is not None
                else None,
                threshold_value=float(row["threshold_value"])
                if row["threshold_value"] is not None
                else None,
            )
            for row in rows
        )

    def append_rating(
        self,
        report_id: UUID,
        owner_id: UUID,
        request: QualityHumanRatingRequest,
    ) -> QualityRatingRecord | None:
        record = QualityRatingRecord(
            id=uuid4(),
            quality_report_id=report_id,
            owner_id=owner_id,
            score=request.score,
            notes=request.notes,
            created_at=utc_now(),
        )
        try:
            with self._engine.begin() as connection:
                if self._get_row(connection, report_id, owner_id) is None:
                    return None
                connection.execute(
                    text(
                        "INSERT INTO quality_ratings "
                        "(id, quality_report_id, owner_id, score, notes, created_at) VALUES "
                        "(:id, :quality_report_id, :owner_id, :score, :notes, :created_at)"
                    ),
                    {
                        "id": str(record.id),
                        "quality_report_id": str(record.quality_report_id),
                        "owner_id": str(record.owner_id),
                        "score": record.score,
                        "notes": record.notes,
                        "created_at": record.created_at.isoformat(),
                    },
                )
        except IntegrityError:
            return None
        return record

    def ratings(self, report_id: UUID, owner_id: UUID) -> tuple[QualityRatingRecord, ...] | None:
        with self._engine.connect() as connection:
            if self._get_row(connection, report_id, owner_id) is None:
                return None
            rows = (
                connection.execute(
                    text(
                        "SELECT id, quality_report_id, owner_id, score, notes, created_at "
                        "FROM quality_ratings WHERE quality_report_id = :report_id "
                        "AND owner_id = :owner_id ORDER BY created_at ASC, id ASC"
                    ),
                    {"report_id": str(report_id), "owner_id": str(owner_id)},
                )
                .mappings()
                .all()
            )
        return tuple(self._rating_from_row(row) for row in rows)

    @staticmethod
    def _lineage_matches(connection: Connection, report: QualityReport) -> bool:
        row = connection.execute(
            text(
                "SELECT 1 FROM projects AS project "
                "JOIN render_jobs AS job ON job.id = :render_job_id "
                "AND job.project_id = project.id AND job.owner_id = project.owner_id "
                "JOIN code_versions AS code ON code.id = :code_version_id "
                "AND code.project_id = project.id AND code.owner_id = project.owner_id "
                "AND job.code_version_id = code.id "
                "JOIN content_plan_versions AS plan ON plan.id = :content_plan_version_id "
                "AND plan.project_id = project.id AND plan.owner_id = project.owner_id "
                "AND code.content_plan_version_id = plan.id "
                "WHERE project.id = :project_id AND project.owner_id = :owner_id"
            ),
            {
                "render_job_id": str(report.render_job_id),
                "code_version_id": str(report.code_version_id),
                "content_plan_version_id": str(report.content_plan_version_id),
                "project_id": str(report.project_id),
                "owner_id": str(report.owner_id),
            },
        ).one_or_none()
        return row is not None

    @staticmethod
    def _project_owned(connection: Connection, project_id: UUID, owner_id: UUID) -> bool:
        return (
            connection.execute(
                text("SELECT 1 FROM projects WHERE id = :project_id AND owner_id = :owner_id"),
                {"project_id": str(project_id), "owner_id": str(owner_id)},
            ).one_or_none()
            is not None
        )

    @staticmethod
    def _cursor_row(
        connection: Connection,
        cursor: UUID | None,
        project_id: UUID,
        owner_id: UUID,
    ):
        if cursor is None:
            return None
        return (
            connection.execute(
                text(
                    "SELECT id, created_at FROM quality_reports WHERE id = :id "
                    "AND project_id = :project_id AND owner_id = :owner_id"
                ),
                {"id": str(cursor), "project_id": str(project_id), "owner_id": str(owner_id)},
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _get_row(connection: Connection, report_id: UUID, owner_id: UUID):
        return (
            connection.execute(
                text("SELECT * FROM quality_reports WHERE id = :id AND owner_id = :owner_id"),
                {"id": str(report_id), "owner_id": str(owner_id)},
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _report_values(report: QualityReport) -> dict[str, object]:
        return {
            "id": str(report.id),
            "project_id": str(report.project_id),
            "owner_id": str(report.owner_id),
            "render_job_id": str(report.render_job_id),
            "code_version_id": str(report.code_version_id),
            "content_plan_version_id": str(report.content_plan_version_id),
            "status": report.status.value,
            "target_duration_seconds": report.target_duration_seconds,
            "estimated_duration_seconds": report.estimated_duration_seconds,
            "actual_duration_seconds": report.actual_duration_seconds,
            "frame_rate": report.frame_rate,
            "frame_count": report.frame_count,
            "score": report.score,
            "repair_count": report.repair_count,
            "diagnostic_signature": report.diagnostic_signature,
            "provider_model": report.provider_model,
            "prompt_template_version": report.prompt_template_version,
            "content_plan_schema_version": report.content_plan_schema_version,
            "manim_version": report.manim_version,
            "image_digest": report.image_digest,
            "ast_policy_version": report.ast_policy_version,
            "diagnostic_policy_version": report.diagnostic_policy_version,
            "created_at": report.created_at.isoformat(),
        }

    @staticmethod
    def _report_from_row(row) -> QualityReport:  # type: ignore[no-untyped-def]
        return QualityReport(
            id=UUID(str(row["id"])),
            project_id=UUID(str(row["project_id"])),
            owner_id=UUID(str(row["owner_id"])),
            render_job_id=UUID(str(row["render_job_id"])),
            code_version_id=UUID(str(row["code_version_id"])),
            content_plan_version_id=UUID(str(row["content_plan_version_id"])),
            status=QualityStatus(str(row["status"])),
            target_duration_seconds=float(row["target_duration_seconds"]),
            estimated_duration_seconds=(
                float(row["estimated_duration_seconds"])
                if row["estimated_duration_seconds"] is not None
                else None
            ),
            actual_duration_seconds=(
                float(row["actual_duration_seconds"])
                if row["actual_duration_seconds"] is not None
                else None
            ),
            frame_rate=float(row["frame_rate"]) if row["frame_rate"] is not None else None,
            frame_count=int(row["frame_count"]) if row["frame_count"] is not None else None,
            score=int(row["score"]) if row["score"] is not None else None,
            repair_count=int(row["repair_count"]),
            diagnostic_signature=str(row["diagnostic_signature"]),
            provider_model=str(row["provider_model"]),
            prompt_template_version=str(row["prompt_template_version"]),
            content_plan_schema_version=str(row["content_plan_schema_version"]),
            manim_version=str(row["manim_version"]),
            image_digest=str(row["image_digest"]),
            ast_policy_version=str(row["ast_policy_version"]),
            diagnostic_policy_version=str(row["diagnostic_policy_version"]),
            created_at=_as_datetime(row["created_at"]),
        )

    @staticmethod
    def _rating_from_row(row) -> QualityRatingRecord:  # type: ignore[no-untyped-def]
        return QualityRatingRecord(
            id=UUID(str(row["id"])),
            quality_report_id=UUID(str(row["quality_report_id"])),
            owner_id=UUID(str(row["owner_id"])),
            score=int(row["score"]),
            notes=str(row["notes"]) if row["notes"] is not None else None,
            created_at=_as_datetime(row["created_at"]),
        )
