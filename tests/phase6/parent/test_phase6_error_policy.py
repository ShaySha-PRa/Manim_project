from manim_workbench_api.content_plans.errors import (
    RETRYABLE_CONTENT_PLAN_ERRORS,
    ContentPlanError,
    ContentPlanErrorCode,
)


def test_retry_policy_is_explicit_and_excludes_auth_and_semantics() -> None:
    assert ContentPlanErrorCode.PROVIDER_RATE_LIMITED in RETRYABLE_CONTENT_PLAN_ERRORS
    assert ContentPlanErrorCode.PROVIDER_INVALID_JSON in RETRYABLE_CONTENT_PLAN_ERRORS
    assert ContentPlanErrorCode.PROVIDER_AUTH_ERROR not in RETRYABLE_CONTENT_PLAN_ERRORS
    assert ContentPlanErrorCode.CONTENT_PLAN_SEMANTIC_ERROR not in RETRYABLE_CONTENT_PLAN_ERRORS


def test_error_exposes_machine_code_without_internal_details() -> None:
    error = ContentPlanError(ContentPlanErrorCode.PROVIDER_UNAVAILABLE, "provider unavailable")
    assert error.code.value == "provider_unavailable"
    assert error.retryable is True
