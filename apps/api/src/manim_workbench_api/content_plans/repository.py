from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from manim_workbench_contracts import (
    ContentPlanDraft,
    ContentPlanGenerationRequest,
    ContentPlanVersion,
    GenerationStatus,
)
from sqlalchemy import Engine, text

from .errors import ContentPlanError, ContentPlanErrorCode
from .models import ProviderResult


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ContentPlanRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def load_prompt(self, request: ContentPlanGenerationRequest) -> str:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT project_id, owner_id, prompt FROM prompt_versions "
                        "WHERE id = :prompt_version_id"
                    ),
                    {"prompt_version_id": str(request.prompt_version_id)},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise ContentPlanError(
                ContentPlanErrorCode.PROMPT_VERSION_NOT_FOUND,
                "Prompt version was not found.",
            )
        if row["project_id"] != str(request.project_id) or row["owner_id"] != str(request.owner_id):
            raise ContentPlanError(
                ContentPlanErrorCode.OWNERSHIP_MISMATCH,
                "Prompt version is not available for this project.",
            )
        return str(row["prompt"])

    def record_failed_attempt(
        self,
        request: ContentPlanGenerationRequest,
        attempt_number: int,
        error_code: ContentPlanErrorCode,
        provider_result: ProviderResult | None = None,
    ) -> None:
        self._insert_attempt(
            request=request,
            attempt_number=attempt_number,
            status=GenerationStatus.FAILED,
            error_code=error_code,
            provider_result=provider_result,
            output_version_id=None,
        )

    def record_non_ready_success(
        self,
        request: ContentPlanGenerationRequest,
        attempt_number: int,
        provider_result: ProviderResult,
    ) -> None:
        self._insert_attempt(
            request=request,
            attempt_number=attempt_number,
            status=GenerationStatus.SUCCEEDED,
            error_code=None,
            provider_result=provider_result,
            output_version_id=None,
        )

    def save_ready(
        self,
        request: ContentPlanGenerationRequest,
        draft: ContentPlanDraft,
        attempt_number: int,
        provider_result: ProviderResult,
    ) -> ContentPlanVersion:
        created_at = utc_now()
        plan_id = uuid4()
        with self._engine.begin() as connection:
            previous = (
                connection.execute(
                    text(
                        "SELECT id, version FROM content_plan_versions "
                        "WHERE project_id = :project_id ORDER BY version DESC LIMIT 1"
                    ),
                    {"project_id": str(request.project_id)},
                )
                .mappings()
                .one_or_none()
            )
            version = 1 if previous is None else int(previous["version"]) + 1
            parent_version_id = None if previous is None else UUID(str(previous["id"]))
            plan = ContentPlanVersion(
                id=plan_id,
                project_id=request.project_id,
                owner_id=request.owner_id,
                version=version,
                parent_version_id=parent_version_id,
                created_at=created_at,
                **draft.model_dump(),
            )
            connection.execute(
                text(
                    """
                    INSERT INTO content_plan_versions (
                        id, project_id, owner_id, version, parent_version_id, created_at,
                        schema_version, content_json
                    ) VALUES (
                        :id, :project_id, :owner_id, :version, :parent_version_id, :created_at,
                        :schema_version, :content_json
                    )
                    """
                ),
                {
                    "id": str(plan.id),
                    "project_id": str(plan.project_id),
                    "owner_id": str(plan.owner_id),
                    "version": plan.version,
                    "parent_version_id": (
                        str(plan.parent_version_id) if plan.parent_version_id else None
                    ),
                    "created_at": plan.created_at.isoformat(),
                    "schema_version": plan.schema_version,
                    "content_json": draft.model_dump_json(),
                },
            )
            self._insert_attempt_with_connection(
                connection=connection,
                request=request,
                attempt_number=attempt_number,
                status=GenerationStatus.SUCCEEDED,
                error_code=None,
                provider_result=provider_result,
                output_version_id=plan.id,
            )
        return plan

    def _insert_attempt(
        self,
        *,
        request: ContentPlanGenerationRequest,
        attempt_number: int,
        status: GenerationStatus,
        error_code: ContentPlanErrorCode | None,
        provider_result: ProviderResult | None,
        output_version_id: UUID | None,
    ) -> None:
        with self._engine.begin() as connection:
            self._insert_attempt_with_connection(
                connection=connection,
                request=request,
                attempt_number=attempt_number,
                status=status,
                error_code=error_code,
                provider_result=provider_result,
                output_version_id=output_version_id,
            )

    @staticmethod
    def _insert_attempt_with_connection(
        *,
        connection,  # type: ignore[no-untyped-def]
        request: ContentPlanGenerationRequest,
        attempt_number: int,
        status: GenerationStatus,
        error_code: ContentPlanErrorCode | None,
        provider_result: ProviderResult | None,
        output_version_id: UUID | None,
    ) -> None:
        connection.execute(
            text(
                """
                INSERT INTO generation_attempts (
                    id, project_id, owner_id, stage, attempt_number, status,
                    input_version_id, output_version_id, error_code, created_at,
                    provider_request_id, provider_model, prompt_tokens, completion_tokens
                ) VALUES (
                    :id, :project_id, :owner_id, 'content_plan', :attempt_number, :status,
                    :input_version_id, :output_version_id, :error_code, :created_at,
                    :provider_request_id, :provider_model, :prompt_tokens, :completion_tokens
                )
                """
            ),
            {
                "id": str(uuid4()),
                "project_id": str(request.project_id),
                "owner_id": str(request.owner_id),
                "attempt_number": attempt_number,
                "status": status.value,
                "input_version_id": str(request.prompt_version_id),
                "output_version_id": str(output_version_id) if output_version_id else None,
                "error_code": error_code.value if error_code else None,
                "created_at": utc_now().isoformat(),
                "provider_request_id": provider_result.request_id if provider_result else None,
                "provider_model": provider_result.model if provider_result else None,
                "prompt_tokens": (provider_result.usage.prompt_tokens if provider_result else None),
                "completion_tokens": (
                    provider_result.usage.completion_tokens if provider_result else None
                ),
            },
        )
