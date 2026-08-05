from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from manim_workbench_api.auth.dependencies import (
    get_mutating_session_principal,
    get_ready_session_principal,
)
from manim_workbench_api.quality.dependencies import get_quality_report_service
from manim_workbench_api.quality.reports import QUALITY_REPORT_NOT_FOUND
from manim_workbench_api.quality.router import router
from manim_workbench_contracts import (
    PipelineStage,
    QualityDiagnostic,
    QualityDiagnosticCode,
    QualityReport,
    QualityReportPage,
    QualitySeverity,
    QualityStatus,
)

OWNER = UUID("00000000-0000-0000-0000-000000000001")
OTHER = UUID("00000000-0000-0000-0000-000000000002")
PROJECT = UUID("00000000-0000-0000-0000-000000000011")
REPORT = UUID("00000000-0000-0000-0000-000000000012")
JOB = UUID("00000000-0000-0000-0000-000000000013")


def quality_report() -> QualityReport:
    return QualityReport(
        id=REPORT,
        project_id=PROJECT,
        owner_id=OWNER,
        render_job_id=JOB,
        code_version_id=UUID("00000000-0000-0000-0000-000000000014"),
        content_plan_version_id=UUID("00000000-0000-0000-0000-000000000015"),
        status=QualityStatus.PASSED,
        target_duration_seconds=90,
        estimated_duration_seconds=89,
        actual_duration_seconds=90,
        frame_rate=30,
        frame_count=2700,
        score=95,
        repair_count=0,
        diagnostic_signature="0" * 64,
        provider_model="offline-test",
        prompt_template_version="phase9-v1",
        content_plan_schema_version="1.1",
        manim_version="0.19.0",
        image_digest=f"sha256:{'1' * 64}",
        ast_policy_version="phase7-v1",
        diagnostic_policy_version="phase9-v1",
        created_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
    )


DIAGNOSTIC = QualityDiagnostic(
    code=QualityDiagnosticCode.DURATION_TOO_SHORT,
    severity=QualitySeverity.WARNING,
    stage=PipelineStage.QUALITY_ANALYSIS,
    message="Video is shorter than the target range.",
    suggestion="Distribute explanation time across teaching steps.",
    measured_value=9,
    threshold_value=81,
)


class FakeQualityService:
    def _owned(self, owner_id: UUID) -> None:
        if owner_id != OWNER:
            raise QUALITY_REPORT_NOT_FOUND

    def get(self, report_id: UUID, owner_id: UUID) -> QualityReport:
        self._owned(owner_id)
        if report_id != REPORT:
            raise QUALITY_REPORT_NOT_FOUND
        return quality_report()

    def diagnostics(self, report_id: UUID, owner_id: UUID):  # type: ignore[no-untyped-def]
        self.get(report_id, owner_id)
        return (DIAGNOSTIC,)

    def list_by_project(self, project_id: UUID, owner_id: UUID, **_):  # type: ignore[no-untyped-def]
        self._owned(owner_id)
        if project_id != PROJECT:
            raise QUALITY_REPORT_NOT_FOUND
        return QualityReportPage(items=(quality_report(),))

    def latest_by_job(self, job_id: UUID, owner_id: UUID) -> QualityReport:
        self._owned(owner_id)
        if job_id != JOB:
            raise QUALITY_REPORT_NOT_FOUND
        return quality_report()

    def append_human_rating(self, report_id, owner_id, request):  # type: ignore[no-untyped-def]
        self.get(report_id, owner_id)
        assert request.score == 88
        return SimpleNamespace()


def client(owner_id: UUID = OWNER) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_quality_report_service] = FakeQualityService
    app.dependency_overrides[get_ready_session_principal] = lambda: SimpleNamespace(
        user_id=owner_id
    )
    app.dependency_overrides[get_mutating_session_principal] = lambda: SimpleNamespace(
        user_id=owner_id
    )
    return TestClient(app)


def test_read_routes_return_frozen_quality_contracts() -> None:
    api = client()
    assert api.get(f"/api/v1/quality-reports/{REPORT}").json()["id"] == str(REPORT)
    assert api.get(f"/api/v1/quality-reports/{REPORT}/diagnostics").json()[0]["code"]
    assert api.get(f"/api/v1/projects/{PROJECT}/quality-reports").json()["items"]
    assert api.get(f"/api/v1/render-jobs/{JOB}/quality-report").status_code == 200


def test_rating_is_append_only_command_with_no_response_body() -> None:
    response = client().post(
        f"/api/v1/quality-reports/{REPORT}/human-rating",
        json={"score": 88, "notes": "clear"},
    )
    assert response.status_code == 204
    assert response.content == b""


def test_cross_owner_and_missing_records_share_the_same_public_404() -> None:
    cross_owner = client(OTHER).get(f"/api/v1/quality-reports/{REPORT}")
    missing = client().get("/api/v1/quality-reports/00000000-0000-0000-0000-000000000099")
    assert cross_owner.status_code == missing.status_code == 404
    assert (
        cross_owner.json()
        == missing.json()
        == {
            "error": {
                "code": "quality_report_not_found",
                "message": "Quality report was not found.",
            }
        }
    )


def test_validation_uses_stable_public_envelope() -> None:
    response = client().get(f"/api/v1/projects/{PROJECT}/quality-reports?limit=0")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
