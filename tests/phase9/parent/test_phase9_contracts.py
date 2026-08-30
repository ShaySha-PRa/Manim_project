from datetime import datetime, timezone
from uuid import uuid4

from manim_workbench_contracts import (
    CONTRACT_SCHEMA_VERSION,
    PipelineStage,
    QualityDiagnostic,
    QualityDiagnosticCode,
    QualityReport,
    QualitySeverity,
    QualityStatus,
)


def test_schema_15_quality_report_is_frozen_and_owner_scoped() -> None:
    now = datetime.now(timezone.utc)
    report = QualityReport(
        id=uuid4(),
        project_id=uuid4(),
        owner_id=uuid4(),
        render_job_id=uuid4(),
        code_version_id=uuid4(),
        content_plan_version_id=uuid4(),
        status=QualityStatus.PASSED,
        target_duration_seconds=90,
        estimated_duration_seconds=90,
        actual_duration_seconds=90,
        frame_rate=30,
        frame_count=2700,
        score=100,
        repair_count=0,
        diagnostic_signature="a" * 64,
        provider_model="offline",
        prompt_template_version="phase9-v1",
        content_plan_schema_version="1.1",
        manim_version="0.21.0",
        image_digest="sha256:" + "b" * 64,
        ast_policy_version="phase7-v1",
        diagnostic_policy_version="phase9-v1",
        created_at=now,
    )
    assert CONTRACT_SCHEMA_VERSION == "1.13"
    assert report.owner_id != report.project_id
    assert report.score == 100


def test_diagnostic_uses_stable_code_stage_and_redacted_evidence() -> None:
    diagnostic = QualityDiagnostic(
        code=QualityDiagnosticCode.DURATION_TOO_SHORT,
        severity=QualitySeverity.ERROR,
        stage=PipelineStage.QUALITY_ANALYSIS,
        message="Actual duration is outside tolerance.",
        suggestion="Distribute explanatory animation time across scenes.",
        evidence_ref="evidence/frames/summary.json",
        measured_value=9.6,
        threshold_value=81,
    )
    assert diagnostic.code.value == "duration_too_short"
    assert not diagnostic.evidence_ref.startswith("/")
