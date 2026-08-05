from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from manim_workbench_api.auth.errors import AuthError
from manim_workbench_contracts import (
    QualityDiagnostic,
    QualityHumanRatingRequest,
    QualityReport,
    QualityReportPage,
)

from .dependencies import MutatingPrincipal, QualityService, ReadyPrincipal
from .reports import QualityReportError


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


class StableQualityRoute(APIRoute):
    """Keep authentication, validation, and domain failures on stable envelopes."""

    def get_route_handler(self):  # type: ignore[no-untyped-def]
        handler = super().get_route_handler()

        async def stable_handler(request):  # type: ignore[no-untyped-def]
            try:
                return await handler(request)
            except RequestValidationError:
                return _error(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "validation_error",
                    "Request was invalid.",
                )
            except AuthError as error:
                return _error(error.status_code, error.code, error.message)
            except QualityReportError as error:
                return _error(error.status_code, error.code, error.message)

        return stable_handler


router = APIRouter(tags=["quality"], route_class=StableQualityRoute)


@router.get("/quality-reports/{report_id}", response_model=QualityReport)
def get_quality_report(
    report_id: UUID,
    principal: ReadyPrincipal,
    service: QualityService,
) -> QualityReport:
    return service.get(report_id, principal.user_id)


@router.get(
    "/quality-reports/{report_id}/diagnostics",
    response_model=tuple[QualityDiagnostic, ...],
)
def list_quality_diagnostics(
    report_id: UUID,
    principal: ReadyPrincipal,
    service: QualityService,
) -> tuple[QualityDiagnostic, ...]:
    return service.diagnostics(report_id, principal.user_id)


@router.get("/projects/{project_id}/quality-reports", response_model=QualityReportPage)
def list_project_quality_reports(
    project_id: UUID,
    principal: ReadyPrincipal,
    service: QualityService,
    cursor: UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> QualityReportPage:
    return service.list_by_project(
        project_id,
        principal.user_id,
        cursor=cursor,
        limit=limit,
    )


@router.get("/render-jobs/{job_id}/quality-report", response_model=QualityReport)
def get_job_quality_report(
    job_id: UUID,
    principal: ReadyPrincipal,
    service: QualityService,
) -> QualityReport:
    return service.latest_by_job(job_id, principal.user_id)


@router.post(
    "/quality-reports/{report_id}/human-rating",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def rate_quality_report(
    report_id: UUID,
    request: QualityHumanRatingRequest,
    principal: MutatingPrincipal,
    service: QualityService,
) -> Response:
    service.append_human_rating(report_id, principal.user_id, request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
