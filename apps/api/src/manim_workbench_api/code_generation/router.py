from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from manim_workbench_contracts import (
    CodeGenerationErrorCode,
    CodeGenerationRequest,
    CodeGenerationResponse,
    CodeVersion,
)
from sqlalchemy import Engine

from manim_workbench_api.jobs.dependencies import get_internal_token, internal_token_is_valid

from .dependencies import (
    get_code_generation_engine,
    get_code_generation_provider,
    get_code_generation_renderer,
)
from .errors import CodeGenerationError
from .models import CandidateRenderer, CodeGenerationProvider
from .repository import CodeGenerationRepository
from .service import CodeGenerationService

router = APIRouter(tags=["code-generations"])

DatabaseEngine = Annotated[Engine, Depends(get_code_generation_engine)]
Provider = Annotated[CodeGenerationProvider, Depends(get_code_generation_provider)]
Renderer = Annotated[CandidateRenderer, Depends(get_code_generation_renderer)]
ExpectedToken = Annotated[str, Depends(get_internal_token)]
RequestToken = Annotated[str | None, Header(alias="X-Internal-Token")]

_ERROR_STATUS = {
    CodeGenerationErrorCode.CONTENT_PLAN_NOT_FOUND: 404,
    CodeGenerationErrorCode.PROVIDER_UNAVAILABLE: 503,
    CodeGenerationErrorCode.PROVIDER_AUTHENTICATION: 502,
    CodeGenerationErrorCode.PROVIDER_CONFIGURATION: 503,
    CodeGenerationErrorCode.PROVIDER_TIMEOUT: 503,
    CodeGenerationErrorCode.INVALID_MODEL_RESPONSE: 502,
    CodeGenerationErrorCode.RESPONSE_TOO_LARGE: 502,
    CodeGenerationErrorCode.AST_PARSE_FAILED: 422,
    CodeGenerationErrorCode.STATIC_POLICY_REPAIRABLE: 422,
    CodeGenerationErrorCode.SECURITY_POLICY_VIOLATION: 422,
    CodeGenerationErrorCode.COMPILE_FAILED: 422,
    CodeGenerationErrorCode.SCENE_STRUCTURE_INVALID: 422,
    CodeGenerationErrorCode.RENDER_FAILED: 422,
    CodeGenerationErrorCode.SANDBOX_TIMEOUT: 503,
    CodeGenerationErrorCode.SANDBOX_RESOURCE_LIMIT: 503,
    CodeGenerationErrorCode.ATTEMPT_BUDGET_EXHAUSTED: 422,
    CodeGenerationErrorCode.CATEGORY_DEGRADED: 503,
    CodeGenerationErrorCode.GENERATION_PAUSED: 503,
    CodeGenerationErrorCode.INTERNAL_ERROR: 500,
}


def _error_response(error: CodeGenerationError) -> JSONResponse:
    return JSONResponse(
        status_code=_ERROR_STATUS[error.code],
        content={"error": {"code": error.code.value, "message": str(error)}},
    )


def _authorized(request_token: str | None, expected_token: str) -> JSONResponse | None:
    if internal_token_is_valid(request_token, expected_token):
        return None
    return JSONResponse(
        status_code=401,
        content={
            "error": {
                "code": "internal_token_invalid",
                "message": "Internal token is invalid.",
            }
        },
    )


@router.post("/code-generations", response_model=CodeGenerationResponse)
def generate_code(
    request: CodeGenerationRequest,
    request_token: RequestToken = None,
    expected_token: ExpectedToken = "",
    engine: DatabaseEngine = None,  # type: ignore[assignment]
    provider: Provider = None,  # type: ignore[assignment]
    renderer: Renderer = None,  # type: ignore[assignment]
) -> CodeGenerationResponse | JSONResponse:
    if unauthorized := _authorized(request_token, expected_token):
        return unauthorized
    try:
        return CodeGenerationService(
            CodeGenerationRepository(engine), provider, renderer
        ).generate(request)
    except CodeGenerationError as error:
        return _error_response(error)


@router.get("/code-versions/{code_version_id}", response_model=CodeVersion)
def get_code_version(
    code_version_id: UUID,
    project_id: Annotated[UUID, Query()],
    owner_id: Annotated[UUID, Query()],
    request_token: RequestToken = None,
    expected_token: ExpectedToken = "",
    engine: DatabaseEngine = None,  # type: ignore[assignment]
) -> CodeVersion | JSONResponse:
    if unauthorized := _authorized(request_token, expected_token):
        return unauthorized
    try:
        return CodeGenerationRepository(engine).get_version(
            code_version_id,
            project_id=project_id,
            owner_id=owner_id,
        )
    except CodeGenerationError as error:
        return _error_response(error)
