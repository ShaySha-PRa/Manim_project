from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import PurePosixPath
from uuid import UUID

from manim_workbench_contracts import (
    QualityDiagnostic,
    QualityHumanRatingRequest,
    QualityReport,
    QualityReportPage,
)

from .errors import (
    QUALITY_REPORT_CONFLICT,
    QUALITY_REPORT_NOT_FOUND,
    QUALITY_REPORT_PROVENANCE_INVALID,
)
from .models import QualityRatingRecord
from .repository import AppendOutcome, QualityReportRepository

_SENSITIVE_VALUE = re.compile(
    r"(?i)(?:api[_-]?key|authorization|cookie|csrf|password|secret|session|token)\s*[:=]\s*\S+"
)
_PROVIDER_SECRET = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_ABSOLUTE_PATH = re.compile(r"(?i)(?:^|\s)(?:[a-z]:[\\/]|/home/|/root/|/etc/|/var/)")
_SOURCE_FRAGMENT = re.compile(
    r"(?im)^\s*(?:from\s+manim\s+import|class\s+GeneratedScene\b|def\s+construct\b)"
)


class QualityReportService:
    """Validates immutable quality evidence before handing it to the repository."""

    def __init__(self, repository: QualityReportRepository) -> None:
        self._repository = repository

    def append_report(
        self,
        report: QualityReport,
        diagnostics: tuple[QualityDiagnostic, ...],
    ) -> QualityReport:
        self._validate_report(report, diagnostics)
        outcome = self._repository.append(report, diagnostics)
        if outcome is AppendOutcome.PROVENANCE_INVALID:
            raise QUALITY_REPORT_PROVENANCE_INVALID
        if outcome is AppendOutcome.CONFLICT:
            raise QUALITY_REPORT_CONFLICT
        return report

    def get(self, report_id: UUID, owner_id: UUID) -> QualityReport:
        report = self._repository.get(report_id, owner_id)
        if report is None:
            raise QUALITY_REPORT_NOT_FOUND
        return report

    def latest_by_job(self, render_job_id: UUID, owner_id: UUID) -> QualityReport:
        report = self._repository.latest_by_job(render_job_id, owner_id)
        if report is None:
            raise QUALITY_REPORT_NOT_FOUND
        return report

    def list_by_project(
        self,
        project_id: UUID,
        owner_id: UUID,
        *,
        cursor: UUID | None,
        limit: int,
    ) -> QualityReportPage:
        if not 1 <= limit <= 100:
            raise QUALITY_REPORT_PROVENANCE_INVALID
        page = self._repository.list_by_project(project_id, owner_id, cursor, limit)
        if page is None:
            raise QUALITY_REPORT_NOT_FOUND
        items, next_cursor = page
        return QualityReportPage(items=items, next_cursor=next_cursor)

    def diagnostics(self, report_id: UUID, owner_id: UUID) -> tuple[QualityDiagnostic, ...]:
        diagnostics = self._repository.diagnostics(report_id, owner_id)
        if diagnostics is None:
            raise QUALITY_REPORT_NOT_FOUND
        return diagnostics

    def append_human_rating(
        self,
        report_id: UUID,
        owner_id: UUID,
        request: QualityHumanRatingRequest,
    ) -> QualityRatingRecord:
        self._validate_text(request.notes)
        rating = self._repository.append_rating(report_id, owner_id, request)
        if rating is None:
            raise QUALITY_REPORT_NOT_FOUND
        return rating

    def ratings(self, report_id: UUID, owner_id: UUID) -> tuple[QualityRatingRecord, ...]:
        ratings = self._repository.ratings(report_id, owner_id)
        if ratings is None:
            raise QUALITY_REPORT_NOT_FOUND
        return ratings

    @staticmethod
    def diagnostic_signature(diagnostics: tuple[QualityDiagnostic, ...]) -> str:
        canonical = [
            QualityReportService._diagnostic_payload(diagnostic) for diagnostic in diagnostics
        ]
        canonical.sort(key=QualityReportService._canonical_json)
        encoded = QualityReportService._canonical_json(canonical).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _validate_report(
        self, report: QualityReport, diagnostics: tuple[QualityDiagnostic, ...]
    ) -> None:
        for value in (
            report.target_duration_seconds,
            report.estimated_duration_seconds,
            report.actual_duration_seconds,
            report.frame_rate,
        ):
            if value is not None and not math.isfinite(value):
                raise QUALITY_REPORT_PROVENANCE_INVALID
        for value in (
            report.provider_model,
            report.prompt_template_version,
            report.content_plan_schema_version,
            report.manim_version,
            report.ast_policy_version,
            report.diagnostic_policy_version,
        ):
            self._validate_text(value)
        for diagnostic in diagnostics:
            self._validate_diagnostic(diagnostic)
        if report.diagnostic_signature != self.diagnostic_signature(diagnostics):
            raise QUALITY_REPORT_PROVENANCE_INVALID

    def _validate_diagnostic(self, diagnostic: QualityDiagnostic) -> None:
        self._validate_text(diagnostic.message)
        self._validate_text(diagnostic.suggestion)
        if diagnostic.evidence_ref is not None:
            self._validate_evidence_ref(diagnostic.evidence_ref)
        for value in (diagnostic.measured_value, diagnostic.threshold_value):
            if value is not None and not math.isfinite(value):
                raise QUALITY_REPORT_PROVENANCE_INVALID

    @staticmethod
    def _validate_evidence_ref(value: str) -> None:
        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            value != normalized
            or normalized.startswith("/")
            or re.match(r"^[A-Za-z]:", normalized) is not None
            or any(part in {"", ".", ".."} for part in path.parts)
            or _SENSITIVE_VALUE.search(normalized)
        ):
            raise QUALITY_REPORT_PROVENANCE_INVALID

    @staticmethod
    def _validate_text(value: str | None) -> None:
        if value is None:
            return
        if (
            _SENSITIVE_VALUE.search(value)
            or _PROVIDER_SECRET.search(value)
            or _ABSOLUTE_PATH.search(value)
            or _SOURCE_FRAGMENT.search(value)
        ):
            raise QUALITY_REPORT_PROVENANCE_INVALID

    @staticmethod
    def _diagnostic_payload(diagnostic: QualityDiagnostic) -> dict[str, object]:
        return {
            "code": diagnostic.code.value,
            "severity": diagnostic.severity.value,
            "stage": diagnostic.stage.value,
            "message": diagnostic.message,
            "suggestion": diagnostic.suggestion,
            "evidence_ref": diagnostic.evidence_ref.replace("\\", "/")
            if diagnostic.evidence_ref
            else None,
            "measured_value": diagnostic.measured_value,
            "threshold_value": diagnostic.threshold_value,
        }

    @staticmethod
    def _canonical_json(value: object) -> str:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
