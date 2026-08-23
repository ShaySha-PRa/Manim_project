from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from manim_workbench_contracts import (
    RenderJobCompletion,
    RenderJobFailureCode,
    RenderJobFailureReport,
    RenderJobHeartbeat,
    RenderJobLease,
    RenderJobLeaseRequest,
    RenderJobSubmission,
)
from sqlalchemy import Engine

from manim_workbench_api.delivery.dependencies import get_artifact_root
from manim_workbench_api.quality.completion import (
    quality_schema_exists,
    record_completed_quality,
)

from .dependencies import (
    JobSignalPublisher,
    get_database_engine,
    get_internal_token,
    get_job_signal_publisher,
    internal_token_is_valid,
)
from .errors import INTERNAL_TOKEN_INVALID, VALIDATION_ERROR, JobError
from .models import JobResponse, LeaseActionRequest, RecoverableJobsResponse
from .repository import JobRepository
from .service import JobService


class StableValidationRoute(APIRoute):
    """Keep request validation errors on the same public error envelope."""

    def get_route_handler(self):  # type: ignore[no-untyped-def]
        original_handler = super().get_route_handler()

        async def stable_validation_handler(request):  # type: ignore[no-untyped-def]
            try:
                return await original_handler(request)
            except RequestValidationError:
                return VALIDATION_ERROR.response()

        return stable_validation_handler


router = APIRouter(tags=["render-jobs"], route_class=StableValidationRoute)

DatabaseEngine = Annotated[Engine, Depends(get_database_engine)]
SignalPublisher = Annotated[JobSignalPublisher, Depends(get_job_signal_publisher)]
InternalToken = Annotated[str, Depends(get_internal_token)]
RequestToken = Annotated[str | None, Header(alias="X-Internal-Token")]


def _service(engine: Engine, publisher: JobSignalPublisher) -> JobService:
    return JobService(JobRepository(engine), publisher)


def _token_error(provided: str | None, expected: str) -> JSONResponse | None:
    if not internal_token_is_valid(provided, expected):
        return INTERNAL_TOKEN_INVALID.response()
    return None


@router.post("/render-jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def submit_render_job(
    submission: RenderJobSubmission,
    request_token: RequestToken = None,
    expected_token: InternalToken = "",
    engine: DatabaseEngine = None,  # type: ignore[assignment]
    publisher: SignalPublisher = None,  # type: ignore[assignment]
) -> JobResponse | JSONResponse:
    if error := _token_error(request_token, expected_token):
        return error
    try:
        job, created = _service(engine, publisher).submit(submission)
        if not created:
            return JSONResponse(status_code=status.HTTP_200_OK, content=job.model_dump(mode="json"))
        return job
    except JobError as error:
        return error.response()


@router.get("/render-jobs/{job_id}", response_model=JobResponse)
def get_render_job(
    job_id: UUID,
    request_token: RequestToken = None,
    expected_token: InternalToken = "",
    engine: DatabaseEngine = None,  # type: ignore[assignment]
    publisher: SignalPublisher = None,  # type: ignore[assignment]
) -> JobResponse | JSONResponse:
    if error := _token_error(request_token, expected_token):
        return error
    try:
        return _service(engine, publisher).get(job_id)
    except JobError as error:
        return error.response()


@router.post("/render-jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_render_job(
    job_id: UUID,
    request_token: RequestToken = None,
    expected_token: InternalToken = "",
    engine: DatabaseEngine = None,  # type: ignore[assignment]
    publisher: SignalPublisher = None,  # type: ignore[assignment]
) -> JobResponse | JSONResponse:
    if error := _token_error(request_token, expected_token):
        return error
    try:
        return _service(engine, publisher).cancel(job_id)
    except JobError as error:
        return error.response()


@router.post("/internal/render-jobs/{job_id}/claim", response_model=RenderJobLease)
def claim_render_job(
    job_id: UUID,
    request: RenderJobLeaseRequest,
    request_token: RequestToken = None,
    expected_token: InternalToken = "",
    engine: DatabaseEngine = None,  # type: ignore[assignment]
    publisher: SignalPublisher = None,  # type: ignore[assignment]
) -> RenderJobLease | JSONResponse:
    if error := _token_error(request_token, expected_token):
        return error
    try:
        return _service(engine, publisher).claim(job_id, request)
    except JobError as error:
        return error.response()


@router.post("/internal/render-jobs/{job_id}/heartbeat", response_model=JobResponse)
def heartbeat_render_job(
    job_id: UUID,
    request: RenderJobHeartbeat,
    request_token: RequestToken = None,
    expected_token: InternalToken = "",
    engine: DatabaseEngine = None,  # type: ignore[assignment]
    publisher: SignalPublisher = None,  # type: ignore[assignment]
) -> JobResponse | JSONResponse:
    if error := _token_error(request_token, expected_token):
        return error
    try:
        return _service(engine, publisher).heartbeat(job_id, request)
    except JobError as error:
        return error.response()


@router.post("/internal/render-jobs/{job_id}/start", response_model=JobResponse)
def start_render_job(
    job_id: UUID,
    request: RenderJobHeartbeat,
    request_token: RequestToken = None,
    expected_token: InternalToken = "",
    engine: DatabaseEngine = None,  # type: ignore[assignment]
    publisher: SignalPublisher = None,  # type: ignore[assignment]
) -> JobResponse | JSONResponse:
    if error := _token_error(request_token, expected_token):
        return error
    try:
        return _service(engine, publisher).start(job_id, request)
    except JobError as error:
        return error.response()


@router.post("/internal/render-jobs/{job_id}/complete", response_model=JobResponse)
def complete_render_job(
    job_id: UUID,
    completion: RenderJobCompletion,
    request_token: RequestToken = None,
    expected_token: InternalToken = "",
    engine: DatabaseEngine = None,  # type: ignore[assignment]
    publisher: SignalPublisher = None,  # type: ignore[assignment]
) -> JobResponse | JSONResponse:
    if error := _token_error(request_token, expected_token):
        return error
    try:
        service = _service(engine, publisher)
        quality_required = quality_schema_exists(engine)
        report = record_completed_quality(
            engine=engine,
            artifact_root=get_artifact_root(),
            job_id=job_id,
            completion=completion,
        )
        if quality_required and (report is None or report.status.value == "failed"):
            return service.fail(
                job_id,
                RenderJobFailureReport(
                    lease_token=completion.lease_token,
                    failure_code=RenderJobFailureCode.RENDER_FAILED,
                ),
            )
        return service.complete(job_id, completion)
    except JobError as error:
        return error.response()


@router.post("/internal/render-jobs/{job_id}/fail", response_model=JobResponse)
def fail_render_job(
    job_id: UUID,
    report: RenderJobFailureReport,
    request_token: RequestToken = None,
    expected_token: InternalToken = "",
    engine: DatabaseEngine = None,  # type: ignore[assignment]
    publisher: SignalPublisher = None,  # type: ignore[assignment]
) -> JobResponse | JSONResponse:
    if error := _token_error(request_token, expected_token):
        return error
    try:
        return _service(engine, publisher).fail(job_id, report)
    except JobError as error:
        return error.response()


@router.get("/internal/render-jobs/recoverable", response_model=RecoverableJobsResponse)
def recoverable_render_jobs(
    limit: int = Query(default=50, ge=1, le=100),
    request_token: RequestToken = None,
    expected_token: InternalToken = "",
    engine: DatabaseEngine = None,  # type: ignore[assignment]
    publisher: SignalPublisher = None,  # type: ignore[assignment]
) -> RecoverableJobsResponse | JSONResponse:
    if error := _token_error(request_token, expected_token):
        return error
    try:
        return _service(engine, publisher).recoverable(limit)
    except JobError as error:
        return error.response()


@router.post("/internal/render-jobs/{job_id}/cancelled", response_model=JobResponse)
def confirm_render_job_cancelled(
    job_id: UUID,
    request: LeaseActionRequest,
    request_token: RequestToken = None,
    expected_token: InternalToken = "",
    engine: DatabaseEngine = None,  # type: ignore[assignment]
    publisher: SignalPublisher = None,  # type: ignore[assignment]
) -> JobResponse | JSONResponse:
    if error := _token_error(request_token, expected_token):
        return error
    try:
        return _service(engine, publisher).confirm_cancelled(job_id, request.lease_token)
    except JobError as error:
        return error.response()
