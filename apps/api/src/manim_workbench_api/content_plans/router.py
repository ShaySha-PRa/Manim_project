from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from manim_workbench_contracts import ContentPlanGenerationRequest
from sqlalchemy import Engine

from manim_workbench_api.jobs.dependencies import get_internal_token, internal_token_is_valid

from .dependencies import get_content_plan_engine, get_content_plan_provider
from .errors import ContentPlanError, ContentPlanErrorCode
from .models import ContentPlanGenerationResponse, ContentPlanProvider
from .repository import ContentPlanRepository
from .service import ContentPlanService

router = APIRouter(tags=["content-plans"])

DatabaseEngine = Annotated[Engine, Depends(get_content_plan_engine)]
Provider = Annotated[ContentPlanProvider, Depends(get_content_plan_provider)]
ExpectedToken = Annotated[str, Depends(get_internal_token)]
RequestToken = Annotated[str | None, Header(alias="X-Internal-Token")]

ERROR_STATUS = {
    ContentPlanErrorCode.CONFIGURATION_ERROR: 503,
    ContentPlanErrorCode.PROVIDER_AUTH_ERROR: 502,
    ContentPlanErrorCode.PROVIDER_RATE_LIMITED: 429,
    ContentPlanErrorCode.PROVIDER_UNAVAILABLE: 503,
    ContentPlanErrorCode.PROVIDER_EMPTY_RESPONSE: 502,
    ContentPlanErrorCode.PROVIDER_TRUNCATED_RESPONSE: 502,
    ContentPlanErrorCode.PROVIDER_INVALID_JSON: 502,
    ContentPlanErrorCode.PROVIDER_SCHEMA_ERROR: 502,
    ContentPlanErrorCode.CONTENT_PLAN_SEMANTIC_ERROR: 422,
    ContentPlanErrorCode.PROMPT_VERSION_NOT_FOUND: 404,
    ContentPlanErrorCode.OWNERSHIP_MISMATCH: 404,
}


def error_response(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


@router.post("/content-plans/generate", response_model=ContentPlanGenerationResponse)
def generate_content_plan(
    request: ContentPlanGenerationRequest,
    request_token: RequestToken = None,
    expected_token: ExpectedToken = "",
    engine: DatabaseEngine = None,  # type: ignore[assignment]
    provider: Provider = None,  # type: ignore[assignment]
) -> ContentPlanGenerationResponse | JSONResponse:
    if not internal_token_is_valid(request_token, expected_token):
        return error_response("internal_token_invalid", "Internal token is invalid.", 401)
    try:
        return ContentPlanService(ContentPlanRepository(engine), provider).generate(request)
    except ContentPlanError as error:
        if error.code is ContentPlanErrorCode.OWNERSHIP_MISMATCH:
            return error_response(
                ContentPlanErrorCode.PROMPT_VERSION_NOT_FOUND.value,
                "Prompt version was not found.",
                404,
            )
        return error_response(error.code.value, str(error), ERROR_STATUS[error.code])
