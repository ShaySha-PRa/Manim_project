from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from manim_workbench_contracts import (
    CodeGenerationCategory,
    CodeGenerationErrorCode,
    CodeGenerationMode,
    CodeGenerationRequest,
    CodeModelResponse,
    CodeVersion,
    ContentPlanDraft,
    ContentPlanVersion,
    GenerationStage,
    GenerationStatus,
)
from sqlalchemy import Engine, text

from .errors import CodeGenerationError
from .models import LoadedCodeGenerationInput
from .repair import CategoryPolicy, CategoryPolicyState


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CodeGenerationRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def load_input(self, request: CodeGenerationRequest) -> LoadedCodeGenerationInput:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT cp.id, cp.project_id, cp.owner_id, cp.version,
                           cp.parent_version_id, cp.created_at, cp.schema_version,
                           cp.content_json
                    FROM content_plan_versions AS cp
                    JOIN prompt_versions AS pv ON pv.id = :prompt_version_id
                    WHERE cp.id = :content_plan_version_id
                      AND cp.project_id = :project_id
                      AND cp.owner_id = :owner_id
                      AND cp.schema_version = '1.1'
                      AND pv.project_id = cp.project_id
                      AND pv.owner_id = cp.owner_id
                    """
                ),
                {
                    "prompt_version_id": str(request.prompt_version_id),
                    "content_plan_version_id": str(request.content_plan_version_id),
                    "project_id": str(request.project_id),
                    "owner_id": str(request.owner_id),
                },
            ).mappings().one_or_none()
        if row is None:
            raise CodeGenerationError(
                CodeGenerationErrorCode.CONTENT_PLAN_NOT_FOUND,
                "Content plan version was not found.",
            )
        try:
            draft = ContentPlanDraft.model_validate_json(row["content_json"])
            plan = ContentPlanVersion(
                id=UUID(str(row["id"])),
                project_id=UUID(str(row["project_id"])),
                owner_id=UUID(str(row["owner_id"])),
                version=int(row["version"]),
                parent_version_id=(
                    UUID(str(row["parent_version_id"])) if row["parent_version_id"] else None
                ),
                created_at=datetime.fromisoformat(str(row["created_at"])),
                **draft.model_dump(),
            )
        except (TypeError, ValueError) as error:
            raise CodeGenerationError(
                CodeGenerationErrorCode.INTERNAL_ERROR,
                "Stored content plan could not be loaded.",
            ) from error
        return LoadedCodeGenerationInput(content_plan=plan)

    def get_version(
        self,
        code_version_id: UUID,
        *,
        project_id: UUID,
        owner_id: UUID,
    ) -> CodeVersion:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT * FROM code_versions WHERE id = :id "
                    "AND project_id = :project_id AND owner_id = :owner_id"
                ),
                {
                    "id": str(code_version_id),
                    "project_id": str(project_id),
                    "owner_id": str(owner_id),
                },
            ).mappings().one_or_none()
        if row is None:
            raise CodeGenerationError(
                CodeGenerationErrorCode.CONTENT_PLAN_NOT_FOUND,
                "Code version was not found.",
            )
        try:
            return CodeVersion(
                id=UUID(str(row["id"])),
                project_id=UUID(str(row["project_id"])),
                owner_id=UUID(str(row["owner_id"])),
                version=int(row["version"]),
                parent_version_id=(
                    UUID(str(row["parent_version_id"])) if row["parent_version_id"] else None
                ),
                created_at=datetime.fromisoformat(str(row["created_at"])),
                prompt_version_id=UUID(str(row["prompt_version_id"])),
                content_plan_version_id=UUID(str(row["content_plan_version_id"])),
                source_code=str(row["source_code"]),
                source_sha256=str(row["source_sha256"]),
                scene_class=str(row["scene_class"]),
                engine=str(row["engine"]),
                engine_version=str(row["engine_version"]),
                category=str(row["category"]),
                generation_mode=str(row["generation_mode"]),
                prompt_template_version=row["prompt_template_version"],
                provider_model=row["provider_model"],
                assumptions=tuple(json.loads(row["assumptions_json"])),
            )
        except (TypeError, ValueError) as error:
            raise CodeGenerationError(
                CodeGenerationErrorCode.INTERNAL_ERROR,
                "Stored code version could not be loaded.",
            ) from error

    def load_category_policies(self) -> dict[CodeGenerationCategory, CategoryPolicy]:
        policies = {category: CategoryPolicy() for category in CodeGenerationCategory}
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT category, status, consecutive_failed_rounds "
                    "FROM code_generation_category_states"
                )
            ).mappings()
            for row in rows:
                category = CodeGenerationCategory(str(row["category"]))
                policies[category] = CategoryPolicy(
                    state=CategoryPolicyState(str(row["status"])),
                    consecutive_failed_quality_rounds=int(row["consecutive_failed_rounds"]),
                )
        return policies

    def save_category_policy(
        self,
        category: CodeGenerationCategory,
        policy: CategoryPolicy,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO code_generation_category_states (
                        category, status, consecutive_failed_rounds, updated_at
                    ) VALUES (:category, :status, :failed_rounds, :updated_at)
                    ON CONFLICT(category) DO UPDATE SET
                        status = excluded.status,
                        consecutive_failed_rounds = excluded.consecutive_failed_rounds,
                        updated_at = excluded.updated_at
                    """
                ),
                {
                    "category": category.value,
                    "status": policy.state.value,
                    "failed_rounds": policy.consecutive_failed_quality_rounds,
                    "updated_at": utc_now().isoformat(),
                },
            )

    def pause_all_categories(self) -> None:
        for category in CodeGenerationCategory:
            current = self.load_category_policies()[category]
            self.save_category_policy(
                category,
                CategoryPolicy(
                    state=CategoryPolicyState.PAUSED,
                    consecutive_failed_quality_rounds=(
                        current.consecutive_failed_quality_rounds
                    ),
                ),
            )

    def record_failed_attempt(
        self,
        request: CodeGenerationRequest,
        *,
        attempt_number: int,
        error_code: CodeGenerationErrorCode,
        provider_model: str | None,
        candidate_sha256: str | None,
        diagnostic_sha256: str | None,
    ) -> None:
        with self._engine.begin() as connection:
            self._insert_attempt(
                connection,
                request=request,
                attempt_number=attempt_number,
                status=GenerationStatus.FAILED,
                error_code=error_code,
                provider_model=provider_model,
                output_version_id=None,
                candidate_sha256=candidate_sha256,
                diagnostic_sha256=diagnostic_sha256,
            )

    def save_success(
        self,
        request: CodeGenerationRequest,
        *,
        response: CodeModelResponse,
        attempt_number: int,
        mode: CodeGenerationMode,
        prompt_template_version: str,
        provider_model: str | None,
    ) -> CodeVersion:
        created_at = utc_now()
        source_sha256 = hashlib.sha256(response.code.encode("utf-8")).hexdigest()
        with self._engine.begin() as connection:
            previous = connection.execute(
                text(
                    "SELECT id, version FROM code_versions "
                    "WHERE project_id = :project_id ORDER BY version DESC LIMIT 1"
                ),
                {"project_id": str(request.project_id)},
            ).mappings().one_or_none()
            version_number = 1 if previous is None else int(previous["version"]) + 1
            parent_version_id = None if previous is None else UUID(str(previous["id"]))
            version = CodeVersion(
                id=uuid4(),
                project_id=request.project_id,
                owner_id=request.owner_id,
                version=version_number,
                parent_version_id=parent_version_id,
                created_at=created_at,
                prompt_version_id=request.prompt_version_id,
                content_plan_version_id=request.content_plan_version_id,
                source_code=response.code,
                source_sha256=source_sha256,
                scene_class=response.scene_class,
                engine="manimce",
                engine_version="0.20.1",
                category=request.category,
                generation_mode=mode,
                prompt_template_version=prompt_template_version,
                provider_model=provider_model,
                assumptions=response.assumptions,
            )
            connection.execute(
                text(
                    """
                    INSERT INTO code_versions (
                        id, project_id, owner_id, version, parent_version_id, created_at,
                        prompt_version_id, content_plan_version_id, source_code, source_sha256,
                        scene_class, engine, engine_version, category, generation_mode,
                        prompt_template_version, provider_model, assumptions_json
                    ) VALUES (
                        :id, :project_id, :owner_id, :version, :parent_version_id, :created_at,
                        :prompt_version_id, :content_plan_version_id, :source_code, :source_sha256,
                        :scene_class, :engine, :engine_version, :category, :generation_mode,
                        :prompt_template_version, :provider_model, :assumptions_json
                    )
                    """
                ),
                {
                    **version.model_dump(
                        mode="json",
                        exclude={"assumptions"},
                    ),
                    "id": str(version.id),
                    "project_id": str(version.project_id),
                    "owner_id": str(version.owner_id),
                    "parent_version_id": (
                        str(version.parent_version_id) if version.parent_version_id else None
                    ),
                    "prompt_version_id": str(version.prompt_version_id),
                    "content_plan_version_id": str(version.content_plan_version_id),
                    "created_at": version.created_at.isoformat(),
                    "category": version.category.value,
                    "generation_mode": version.generation_mode.value,
                    "assumptions_json": json.dumps(
                        list(version.assumptions), ensure_ascii=False, separators=(",", ":")
                    ),
                },
            )
            self._insert_attempt(
                connection,
                request=request,
                attempt_number=attempt_number,
                status=GenerationStatus.SUCCEEDED,
                error_code=None,
                provider_model=provider_model,
                output_version_id=version.id,
                candidate_sha256=source_sha256,
                diagnostic_sha256=None,
            )
        return version

    @staticmethod
    def _insert_attempt(
        connection,  # type: ignore[no-untyped-def]
        *,
        request: CodeGenerationRequest,
        attempt_number: int,
        status: GenerationStatus,
        error_code: CodeGenerationErrorCode | None,
        provider_model: str | None,
        output_version_id: UUID | None,
        candidate_sha256: str | None,
        diagnostic_sha256: str | None,
    ) -> None:
        stage = GenerationStage.CODE if attempt_number == 1 else GenerationStage.REPAIR
        connection.execute(
            text(
                """
                INSERT INTO generation_attempts (
                    id, project_id, owner_id, stage, attempt_number, status,
                    input_version_id, output_version_id, error_code, created_at,
                    provider_request_id, provider_model, prompt_tokens, completion_tokens,
                    candidate_sha256, diagnostic_sha256
                ) VALUES (
                    :id, :project_id, :owner_id, :stage, :attempt_number, :status,
                    :input_version_id, :output_version_id, :error_code, :created_at,
                    NULL, :provider_model, NULL, NULL, :candidate_sha256, :diagnostic_sha256
                )
                """
            ),
            {
                "id": str(uuid4()),
                "project_id": str(request.project_id),
                "owner_id": str(request.owner_id),
                "stage": stage.value,
                "attempt_number": attempt_number,
                "status": status.value,
                "input_version_id": str(request.content_plan_version_id),
                "output_version_id": str(output_version_id) if output_version_id else None,
                "error_code": error_code.value if error_code else None,
                "created_at": utc_now().isoformat(),
                "provider_model": provider_model,
                "candidate_sha256": candidate_sha256,
                "diagnostic_sha256": diagnostic_sha256,
            },
        )
