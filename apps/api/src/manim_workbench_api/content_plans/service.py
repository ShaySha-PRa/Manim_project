from __future__ import annotations

import json
from typing import Any

from manim_workbench_contracts import (
    ContentPlanGenerationRequest,
    ContentPlanModelResponse,
    ContentPlanOutcome,
)
from pydantic import ValidationError

from .errors import ContentPlanError, ContentPlanErrorCode
from .models import ContentPlanGenerationResponse, ContentPlanProvider, ProviderResult
from .repository import ContentPlanRepository


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


class ContentPlanService:
    def __init__(
        self,
        repository: ContentPlanRepository,
        provider: ContentPlanProvider,
    ) -> None:
        self._repository = repository
        self._provider = provider

    def generate(self, request: ContentPlanGenerationRequest) -> ContentPlanGenerationResponse:
        from .prompts import build_content_plan_messages
        from .validation import validate_content_plan_response

        source_prompt = self._repository.load_prompt(request)
        messages = build_content_plan_messages(source_prompt, request)
        for attempt_number in (1, 2):
            provider_result: ProviderResult | None = None
            try:
                provider_result = self._provider.generate(messages)
                model_response = self._parse(provider_result)
                model_response = validate_content_plan_response(
                    model_response,
                    request,
                    source_prompt,
                )
            except ContentPlanError as error:
                self._repository.record_failed_attempt(
                    request,
                    attempt_number,
                    error.code,
                    provider_result,
                )
                if error.retryable and attempt_number == 1:
                    continue
                raise

            if model_response.outcome is ContentPlanOutcome.READY:
                assert model_response.plan is not None
                version = self._repository.save_ready(
                    request,
                    model_response.plan,
                    attempt_number,
                    provider_result,
                )
                return ContentPlanGenerationResponse(
                    outcome=model_response.outcome,
                    content_plan_version=version,
                    attempts_used=attempt_number,
                )

            self._repository.record_non_ready_success(
                request,
                attempt_number,
                provider_result,
            )
            return ContentPlanGenerationResponse(
                outcome=model_response.outcome,
                clarifications=model_response.clarifications,
                limitations=model_response.limitations,
                attempts_used=attempt_number,
            )
        raise AssertionError("two-attempt loop must return or raise")

    @staticmethod
    def _parse(result: ProviderResult) -> ContentPlanModelResponse:
        if not result.content.strip():
            raise ContentPlanError(
                ContentPlanErrorCode.PROVIDER_EMPTY_RESPONSE,
                "Provider returned an empty response.",
            )
        if result.finish_reason == "length":
            raise ContentPlanError(
                ContentPlanErrorCode.PROVIDER_TRUNCATED_RESPONSE,
                "Provider response was truncated.",
            )
        try:
            payload = json.loads(result.content, object_pairs_hook=_reject_duplicate_keys)
        except (json.JSONDecodeError, ValueError) as error:
            raise ContentPlanError(
                ContentPlanErrorCode.PROVIDER_INVALID_JSON,
                "Provider returned invalid JSON.",
            ) from error
        try:
            return ContentPlanModelResponse.model_validate(payload)
        except ValidationError as error:
            raise ContentPlanError(
                ContentPlanErrorCode.PROVIDER_SCHEMA_ERROR,
                "Provider response did not match the ContentPlan schema.",
            ) from error
