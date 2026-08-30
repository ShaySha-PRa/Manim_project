"""Bounded, auditable workflow Director planning orchestration."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol
from uuid import UUID, uuid4

from manim_workbench_contracts import (
    DirectorDraft,
    DirectorPlan,
    DirectorPlanRequest,
    DirectorPlanStatus,
)

from manim_workbench_api.content_plans.errors import ContentPlanError
from manim_workbench_api.content_plans.models import ProviderMessage, ProviderResult

from . import DirectorCandidateError, parse_director_candidate
from .prompts import (
    DIRECTOR_PROMPT_TEMPLATE_VERSION,
    build_director_messages,
    build_director_repair_messages,
)
from .repository import DirectorAttempt, DirectorRepository


class DirectorProvider(Protocol):
    def generate(self, messages: tuple[ProviderMessage, ...]) -> ProviderResult: ...


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_request(request: DirectorPlanRequest) -> str:
    payload = request.model_dump(mode="json", exclude={"idempotency_key"})
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _prompt_sha256(messages: tuple[ProviderMessage, ...]) -> str:
    return _sha256(
        json.dumps(
            [message.model_dump() for message in messages],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


class DirectorPlanningService:
    def __init__(self, repository: DirectorRepository, provider: DirectorProvider) -> None:
        self._repository = repository
        self._provider = provider

    def create(
        self, request: DirectorPlanRequest, owner_id: UUID
    ) -> tuple[DirectorPlan, bool]:
        canonical = _canonical_request(request)
        input_sha256 = _sha256(canonical)
        cache_key = _sha256(
            f"{DIRECTOR_PROMPT_TEMPLATE_VERSION}\0{input_sha256}"
        )
        return self._repository.create_or_get(
            request,
            owner_id=owner_id,
            cache_key=cache_key,
            input_sha256=input_sha256,
            prompt_template_version=DIRECTOR_PROMPT_TEMPLATE_VERSION,
        )

    def execute(self, plan_id: UUID, project_id: UUID, owner_id: UUID) -> DirectorPlan:
        plan = self._repository.get(plan_id, project_id, owner_id)
        if plan.status in {
            DirectorPlanStatus.READY,
            DirectorPlanStatus.NEEDS_CONFIRMATION,
            DirectorPlanStatus.FAILED,
            DirectorPlanStatus.CANCELLED,
        }:
            return plan
        if plan.status is DirectorPlanStatus.QUEUED:
            plan = self._repository.transition(
                plan.id,
                project_id,
                owner_id,
                expected_state_version=plan.state_version,
                status=DirectorPlanStatus.PLANNING,
            )
        messages = build_director_messages(plan.request)
        for attempt_number in (1, 2):
            result: ProviderResult | None = None
            try:
                result = self._provider.generate(messages)
                draft = parse_director_candidate(result.content)
                self._validate_semantics(plan.request, draft)
            except ContentPlanError as error:
                self._append_failed_attempt(
                    plan, owner_id, attempt_number, messages, error.code.value, result
                )
                return self._fail(plan, project_id, owner_id, attempt_number, error.code.value)
            except DirectorCandidateError as error:
                self._append_failed_attempt(
                    plan, owner_id, attempt_number, messages, error.code, result
                )
                if attempt_number == 1 and error.code in {
                    "director_invalid_json",
                    "director_invalid_schema",
                }:
                    messages = build_director_repair_messages(
                        plan.request, f"{error.code}: {error}"
                    )
                    continue
                return self._fail(plan, project_id, owner_id, attempt_number, error.code)

            assert result is not None
            output_sha256 = _sha256(draft.model_dump_json())
            self._repository.append_attempt(
                self._attempt(
                    plan,
                    owner_id,
                    attempt_number,
                    messages,
                    status="succeeded",
                    result=result,
                    candidate_sha256=output_sha256,
                )
            )
            stopped = bool(draft.confirmations)
            return self._repository.transition(
                plan.id,
                project_id,
                owner_id,
                expected_state_version=plan.state_version,
                status=(
                    DirectorPlanStatus.NEEDS_CONFIRMATION
                    if stopped
                    else DirectorPlanStatus.READY
                ),
                draft=draft,
                output_sha256=output_sha256,
                attempt_count=attempt_number,
                provider_model=result.model,
                error_code="needs_confirmation" if stopped else None,
            )
        raise AssertionError("two-attempt Director loop must return")

    @staticmethod
    def _validate_semantics(request: DirectorPlanRequest, draft: DirectorDraft) -> None:
        brief = draft.global_brief
        if brief.language is not request.language:
            raise DirectorCandidateError(
                "director_invalid_schema", "language must preserve the request"
            )
        if brief.target_duration_seconds != request.target_duration_seconds:
            raise DirectorCandidateError(
                "director_invalid_schema", "duration must preserve the request"
            )
        if request.style_preset is not None and brief.style_preset is not request.style_preset:
            raise DirectorCandidateError(
                "director_invalid_schema", "style must preserve the request"
            )
        confirmation_positions = {
            item.scene_position
            for item in draft.confirmations
            if item.kind == "asset_required"
        }
        for position, scene in enumerate(draft.scenes, start=1):
            if scene.asset_requirements and position not in confirmation_positions:
                raise DirectorCandidateError(
                    "director_invalid_schema",
                    "asset requirements must have an asset_required confirmation",
                )

    def _fail(
        self,
        plan: DirectorPlan,
        project_id: UUID,
        owner_id: UUID,
        attempt_count: int,
        error_code: str,
    ) -> DirectorPlan:
        return self._repository.transition(
            plan.id,
            project_id,
            owner_id,
            expected_state_version=plan.state_version,
            status=DirectorPlanStatus.FAILED,
            attempt_count=attempt_count,
            error_code=error_code,
        )

    def _append_failed_attempt(
        self,
        plan: DirectorPlan,
        owner_id: UUID,
        attempt_number: int,
        messages: tuple[ProviderMessage, ...],
        error_code: str,
        result: ProviderResult | None,
    ) -> None:
        diagnostic_sha256 = _sha256(error_code)
        candidate_sha256 = _sha256(result.content) if result is not None else None
        self._repository.append_attempt(
            self._attempt(
                plan,
                owner_id,
                attempt_number,
                messages,
                status="failed",
                result=result,
                candidate_sha256=candidate_sha256,
                diagnostic_sha256=diagnostic_sha256,
                error_code=error_code,
            )
        )

    @staticmethod
    def _attempt(
        plan: DirectorPlan,
        owner_id: UUID,
        attempt_number: int,
        messages: tuple[ProviderMessage, ...],
        *,
        status: str,
        result: ProviderResult | None,
        candidate_sha256: str | None,
        diagnostic_sha256: str | None = None,
        error_code: str | None = None,
    ) -> DirectorAttempt:
        from .repository import _now

        return DirectorAttempt(
            id=uuid4(),
            plan_id=plan.id,
            owner_id=owner_id,
            attempt_number=attempt_number,
            status=status,
            provider_model=result.model if result is not None else None,
            provider_request_id=result.request_id if result is not None else None,
            prompt_template_version=DIRECTOR_PROMPT_TEMPLATE_VERSION,
            prompt_sha256=_prompt_sha256(messages),
            prompt_tokens=result.usage.prompt_tokens if result is not None else None,
            completion_tokens=(
                result.usage.completion_tokens if result is not None else None
            ),
            candidate_sha256=candidate_sha256,
            diagnostic_sha256=diagnostic_sha256,
            error_code=error_code,
            created_at=_now(),
        )


__all__ = ["DirectorPlanningService", "DirectorProvider"]
