from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QualityReportError(Exception):
    """A stable, public-safe report-domain error for router integration."""

    status_code: int
    code: str
    message: str


QUALITY_REPORT_NOT_FOUND = QualityReportError(
    404, "quality_report_not_found", "Quality report was not found."
)
QUALITY_REPORT_PROVENANCE_INVALID = QualityReportError(
    422, "quality_report_provenance_invalid", "Quality report provenance was invalid."
)
QUALITY_REPORT_CONFLICT = QualityReportError(
    409, "quality_report_conflict", "Quality report conflicts with immutable history."
)
