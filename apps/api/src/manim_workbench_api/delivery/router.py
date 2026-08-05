from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.routing import APIRoute

from manim_workbench_api.auth.errors import AuthError
from manim_workbench_api.auth.models import SessionPrincipal

from .dependencies import get_delivery_service, get_session_principal
from .service import DeliveryNotFound, DeliveryService, EventCursor


class StableDeliveryRoute(APIRoute):
    """Keep auth and input failures on the browser's frozen error envelope."""

    def get_route_handler(self):  # type: ignore[no-untyped-def]
        handler = super().get_route_handler()

        async def stable_handler(request):  # type: ignore[no-untyped-def]
            try:
                return await handler(request)
            except AuthError as error:
                return _error(error.status_code, error.code, error.message)
            except RequestValidationError:
                return _error(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "validation_error",
                    "Request was invalid.",
                )

        return stable_handler


router = APIRouter(tags=["delivery"], route_class=StableDeliveryRoute)

Principal = Annotated[SessionPrincipal, Depends(get_session_principal)]
Service = Annotated[DeliveryService, Depends(get_delivery_service)]
LastEventId = Annotated[str | None, Header(alias="Last-Event-ID")]


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _ready(principal: SessionPrincipal) -> JSONResponse | None:
    if not principal.is_ready:
        return _error(
            status.HTTP_403_FORBIDDEN,
            "authorization_failed",
            "Request was not authorized.",
        )
    return None


@router.get("/render-jobs/{job_id}/events", response_model=None)
def render_job_events(
    job_id: UUID,
    principal: Principal,
    service: Service,
    last_event_id: LastEventId = None,
) -> StreamingResponse | JSONResponse:
    if error := _ready(principal):
        return error
    try:
        cursor = EventCursor.parse(last_event_id)
        # Validate before response start; streaming exceptions cannot be redacted safely.
        service.events(principal, job_id, cursor)
    except ValueError:
        return _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_event_cursor",
            "Event cursor was invalid.",
        )
    except DeliveryNotFound as error:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=error.public_payload())
    return StreamingResponse(
        service.event_stream(principal, job_id, cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/artifacts/{artifact_id}", response_model=None)
def preview_artifact(
    artifact_id: UUID,
    principal: Principal,
    service: Service,
) -> FileResponse | JSONResponse:
    if error := _ready(principal):
        return error
    try:
        artifact = service.artifact(principal, artifact_id, attachment=False)
    except DeliveryNotFound as error:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=error.public_payload())
    return FileResponse(artifact.path, media_type=artifact.media_type, headers=artifact.headers)


@router.get("/artifacts/{artifact_id}/download", response_model=None)
def download_artifact(
    artifact_id: UUID,
    principal: Principal,
    service: Service,
) -> FileResponse | JSONResponse:
    if error := _ready(principal):
        return error
    try:
        artifact = service.artifact(principal, artifact_id, attachment=True)
    except DeliveryNotFound as error:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=error.public_payload())
    return FileResponse(
        artifact.path,
        media_type=artifact.media_type,
        headers=artifact.headers,
        filename=artifact.filename,
        content_disposition_type="attachment",
    )
