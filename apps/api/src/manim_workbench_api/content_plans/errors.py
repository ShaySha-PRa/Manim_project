from __future__ import annotations

from enum import Enum


class ContentPlanErrorCode(str, Enum):
    CONFIGURATION_ERROR = "configuration_error"
    PROVIDER_AUTH_ERROR = "provider_auth_error"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_EMPTY_RESPONSE = "provider_empty_response"
    PROVIDER_TRUNCATED_RESPONSE = "provider_truncated_response"
    PROVIDER_INVALID_JSON = "provider_invalid_json"
    PROVIDER_SCHEMA_ERROR = "provider_schema_error"
    CONTENT_PLAN_SEMANTIC_ERROR = "content_plan_semantic_error"
    PROMPT_VERSION_NOT_FOUND = "prompt_version_not_found"
    OWNERSHIP_MISMATCH = "ownership_mismatch"


RETRYABLE_CONTENT_PLAN_ERRORS = frozenset(
    {
        ContentPlanErrorCode.PROVIDER_RATE_LIMITED,
        ContentPlanErrorCode.PROVIDER_UNAVAILABLE,
        ContentPlanErrorCode.PROVIDER_EMPTY_RESPONSE,
        ContentPlanErrorCode.PROVIDER_TRUNCATED_RESPONSE,
        ContentPlanErrorCode.PROVIDER_INVALID_JSON,
        ContentPlanErrorCode.PROVIDER_SCHEMA_ERROR,
    }
)


class ContentPlanError(RuntimeError):
    def __init__(self, code: ContentPlanErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_CONTENT_PLAN_ERRORS


class ContentPlanSemanticError(ContentPlanError):
    def __init__(self, message: str) -> None:
        super().__init__(ContentPlanErrorCode.CONTENT_PLAN_SEMANTIC_ERROR, message)
