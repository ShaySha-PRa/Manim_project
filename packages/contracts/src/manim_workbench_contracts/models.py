from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator
from typing_extensions import TypeAliasType

CONTRACT_SCHEMA_VERSION = "1.6"

ShortText = Annotated[str, Field(min_length=1, max_length=200)]
LongText = Annotated[str, Field(min_length=1, max_length=20_000)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
RelativePath = Annotated[str, Field(min_length=1, max_length=500)]
JsonValue = TypeAliasType(
    "JsonValue",
    str | bool | int | FiniteFloat | None | list["JsonValue"] | dict[str, "JsonValue"],
)
JsonObject = dict[str, JsonValue]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)


class Audience(str, Enum):
    PRIMARY_SCHOOL = "primary_school"
    MIDDLE_SCHOOL = "middle_school"
    HIGH_SCHOOL = "high_school"
    UNDERGRADUATE = "undergraduate"
    GENERAL_AUDIENCE = "general_audience"


class Language(str, Enum):
    ZH_CN = "zh-CN"
    EN_US = "en-US"


class DerivationStyle(str, Enum):
    STEP_BY_STEP = "step_by_step"
    CONCEPTUAL = "conceptual"
    PROOF_ORIENTED = "proof_oriented"
    VISUAL_INTUITION = "visual_intuition"


class ContentPlanOutcome(str, Enum):
    READY = "ready"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED = "unsupported"


class CodeGenerationCategory(str, Enum):
    FORMULA_DERIVATION = "formula_derivation"
    FUNCTION_VISUALIZATION = "function_visualization"


class CodeGenerationMode(str, Enum):
    FULL = "full"
    DETERMINISTIC_TEMPLATE = "deterministic_template"


class CodeGenerationOutcome(str, Enum):
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    PAUSED = "paused"


class CodeGenerationErrorCode(str, Enum):
    CONTENT_PLAN_NOT_FOUND = "content_plan_not_found"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_AUTHENTICATION = "provider_authentication"
    PROVIDER_CONFIGURATION = "provider_configuration"
    PROVIDER_TIMEOUT = "provider_timeout"
    INVALID_MODEL_RESPONSE = "invalid_model_response"
    RESPONSE_TOO_LARGE = "response_too_large"
    AST_PARSE_FAILED = "ast_parse_failed"
    STATIC_POLICY_REPAIRABLE = "static_policy_repairable"
    SECURITY_POLICY_VIOLATION = "security_policy_violation"
    COMPILE_FAILED = "compile_failed"
    SCENE_STRUCTURE_INVALID = "scene_structure_invalid"
    RENDER_FAILED = "render_failed"
    SANDBOX_TIMEOUT = "sandbox_timeout"
    SANDBOX_RESOURCE_LIMIT = "sandbox_resource_limit"
    ATTEMPT_BUDGET_EXHAUSTED = "attempt_budget_exhausted"
    CATEGORY_DEGRADED = "category_degraded"
    GENERATION_PAUSED = "generation_paused"
    INTERNAL_ERROR = "internal_error"


class ClarificationField(str, Enum):
    AUDIENCE = "audience"
    DURATION = "duration"
    DERIVATION_STYLE = "derivation_style"
    ASSUMPTIONS = "assumptions"
    MATHEMATICAL_INTENT = "mathematical_intent"


class RenderProfile(str, Enum):
    PREVIEW = "preview"
    FINAL = "final"


class RenderJobStatus(str, Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RenderJobFailureCode(str, Enum):
    RENDER_FAILED = "render_failed"
    SANDBOX_TIMEOUT = "sandbox_timeout"
    SANDBOX_OOM = "sandbox_oom"
    SANDBOX_PID_LIMIT = "sandbox_pid_limit"
    SANDBOX_OUTPUT_LIMIT = "sandbox_output_limit"
    SANDBOX_SECURITY_VIOLATION = "sandbox_security_violation"
    ARTIFACT_PUBLISH_FAILED = "artifact_publish_failed"
    LEASE_EXPIRED = "lease_expired"
    RUNNER_LOST = "runner_lost"


class ArtifactKind(str, Enum):
    VIDEO = "video"
    THUMBNAIL = "thumbnail"
    RENDER_LOG = "render_log"
    METADATA = "metadata"


class GenerationStage(str, Enum):
    CONTENT_PLAN = "content_plan"
    CODE = "code"
    REPAIR = "repair"


class GenerationStatus(str, Enum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PipelineStage(str, Enum):
    PROMPT = "prompt"
    CONTENT_PLAN = "content_plan"
    CODE_GENERATION = "code_generation"
    PREVIEW_RENDER = "preview_render"
    FINAL_RENDER = "final_render"
    ARTIFACT_DELIVERY = "artifact_delivery"
    QUALITY_ANALYSIS = "quality_analysis"
    QUALITY_RECOVERY = "quality_recovery"


class QualityStatus(str, Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    REPAIR_REQUIRED = "repair_required"
    REPAIRING = "repairing"
    PASSED = "passed"
    DEGRADED = "degraded"
    FAILED = "failed"


class QualitySeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class QualityDiagnosticCode(str, Enum):
    SOURCE_NOT_APPROVED = "source_not_approved"
    DEFAULT_PLAY_DURATION_ASSUMED = "default_play_duration_assumed"
    DURATION_TOO_SHORT = "duration_too_short"
    DURATION_TOO_LONG = "duration_too_long"
    PREVIEW_FINAL_TIMELINE_MISMATCH = "preview_final_timeline_mismatch"
    LONG_STATIC_SEGMENT = "long_static_segment"
    BLANK_FRAME = "blank_frame"
    OBJECT_OUT_OF_BOUNDS = "object_out_of_bounds"
    OBJECT_OVERLAP = "object_overlap"
    TEXT_TOO_SMALL = "text_too_small"
    CJK_GLYPH_MISSING = "cjk_glyph_missing"
    KEY_FORMULA_MISSING = "key_formula_missing"
    OBJECT_MISSING = "object_missing"
    ANIMATION_ORDER_MISMATCH = "animation_order_mismatch"
    TIMELINE_UNKNOWN = "timeline_unknown"
    TERMINAL_WAIT_PADDING = "terminal_wait_padding"
    MEDIA_METADATA_INVALID = "media_metadata_invalid"
    MEDIA_METADATA_INCONSISTENT = "media_metadata_inconsistent"
    PLANNED_SCENE_MISSING = "planned_scene_missing"


class SessionState(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class ExperimentDomainKind(str, Enum):
    GENERIC = "generic"
    GEOMETRY = "geometry"
    ODE = "ode"
    PDE = "pde"
    FEM = "fem"
    STOCHASTIC = "stochastic"
    OPTIMIZATION = "optimization"
    NEURAL_NETWORK = "neural_network"
    CUSTOM_PYTHON = "custom_python"


class AssumptionSource(str, Enum):
    USER = "user"
    MODEL = "model"
    IMPORT = "import"
    SYSTEM = "system"


class AssumptionStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ExperimentPatchProposalStatus(str, Enum):
    PENDING = "pending"
    APPLIED = "applied"
    REJECTED = "rejected"


class ExperimentPatchOperationKind(str, Enum):
    ADD = "add"
    REPLACE = "replace"
    REMOVE = "remove"


class ModelSpec(ContractModel):
    schema_version: Literal["1.0"]
    domain_kind: ExperimentDomainKind
    plugin_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{2,99}$")]
    plugin_version: Annotated[str, Field(min_length=1, max_length=50)]
    payload: JsonObject

    @field_validator("payload")
    @classmethod
    def validate_payload_size(cls, value: JsonObject) -> JsonObject:
        canonical_payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        if len(canonical_payload.encode("utf-8")) > 200_000:
            raise ValueError("payload canonical JSON must be at most 200000 UTF-8 bytes")
        return value


class User(ContractModel):
    id: UUID
    email: Annotated[str, Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")]
    created_at: datetime


class AuthenticatedUser(ContractModel):
    id: UUID
    email: Annotated[str, Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")]
    must_change_password: bool
    created_at: datetime


class LoginRequest(ContractModel):
    email: Annotated[str, Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")]
    password: Annotated[str, Field(min_length=12, max_length=1_024)]


class LoginResponse(ContractModel):
    user: AuthenticatedUser
    csrf_token: Annotated[str, Field(min_length=32, max_length=256)]
    expires_at: datetime


class PasswordChangeRequest(ContractModel):
    current_password: Annotated[str, Field(min_length=12, max_length=1_024)]
    new_password: Annotated[str, Field(min_length=14, max_length=1_024)]


class LogoutResponse(ContractModel):
    ok: Literal[True]


class ApiErrorDetail(ContractModel):
    code: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,99}$")]
    message: Annotated[str, Field(min_length=1, max_length=1_000)]
    stage: PipelineStage | None = None


class ApiErrorResponse(ContractModel):
    error: ApiErrorDetail


class Project(ContractModel):
    id: UUID
    owner_id: UUID
    title: ShortText
    created_at: datetime
    archived_at: datetime | None = None


class ProjectCreateRequest(ContractModel):
    title: ShortText


class ProjectUpdateRequest(ContractModel):
    title: ShortText | None = None
    archived: bool | None = None

    @model_validator(mode="after")
    def require_update(self) -> ProjectUpdateRequest:
        if self.title is None and self.archived is None:
            raise ValueError("at least one project field must be provided")
        return self


class ProjectPage(ContractModel):
    items: Annotated[tuple[Project, ...], Field(max_length=100)]
    next_cursor: UUID | None = None


class ExperimentParameter(ContractModel):
    key: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,99}$")]
    label: ShortText
    value: JsonValue
    unit: Annotated[str | None, Field(max_length=100)] = None
    editable: bool = True


class ExperimentObservable(ContractModel):
    key: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,99}$")]
    label: ShortText
    description: Annotated[str | None, Field(max_length=2_000)] = None
    unit: Annotated[str | None, Field(max_length=100)] = None


class ExperimentAssumption(ContractModel):
    id: UUID
    statement: Annotated[str, Field(min_length=1, max_length=2_000)]
    source: AssumptionSource
    status: AssumptionStatus
    created_at: datetime


class ExperimentCodeFile(ContractModel):
    path: RelativePath
    language: Literal["python"]
    content: Annotated[str, Field(max_length=200_000)]

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("path must stay inside the artifact directory")
        return value


class Experiment(ContractModel):
    id: UUID
    project_id: UUID
    owner_id: UUID
    title: ShortText
    created_at: datetime
    archived_at: datetime | None = None


class ExperimentCreateRequest(ContractModel):
    title: ShortText
    domain_kind: ExperimentDomainKind = ExperimentDomainKind.GENERIC


class ExperimentPage(ContractModel):
    items: Annotated[tuple[Experiment, ...], Field(max_length=100)]
    next_cursor: UUID | None = None


def _validate_unique_experiment_code_file_paths(
    code_files: tuple[ExperimentCodeFile, ...],
) -> None:
    if len({code_file.path for code_file in code_files}) != len(code_files):
        raise ValueError("code_files must not contain duplicate paths")


class ExperimentDraft(ContractModel):
    experiment_id: UUID
    project_id: UUID
    owner_id: UUID
    revision: Annotated[int, Field(ge=1)]
    model_spec: ModelSpec
    parameters: Annotated[tuple[ExperimentParameter, ...], Field(max_length=200)]
    observables: Annotated[tuple[ExperimentObservable, ...], Field(max_length=200)]
    assumptions: Annotated[tuple[ExperimentAssumption, ...], Field(max_length=100)]
    visualization: JsonObject = Field(default_factory=dict)
    code_files: Annotated[tuple[ExperimentCodeFile, ...], Field(max_length=20)]
    updated_at: datetime

    @model_validator(mode="after")
    def validate_unique_code_file_paths(self) -> ExperimentDraft:
        _validate_unique_experiment_code_file_paths(self.code_files)
        return self


class ExperimentDraftUpdateRequest(ContractModel):
    expected_revision: Annotated[int, Field(ge=1)]
    model_spec: ModelSpec | None = None
    parameters: Annotated[tuple[ExperimentParameter, ...], Field(max_length=200)] | None = None
    observables: Annotated[tuple[ExperimentObservable, ...], Field(max_length=200)] | None = None
    assumptions: Annotated[tuple[ExperimentAssumption, ...], Field(max_length=100)] | None = None
    visualization: JsonObject | None = None
    code_files: Annotated[tuple[ExperimentCodeFile, ...], Field(max_length=20)] | None = None

    @model_validator(mode="after")
    def validate_replacements(self) -> ExperimentDraftUpdateRequest:
        replacement_fields = {
            "model_spec",
            "parameters",
            "observables",
            "assumptions",
            "visualization",
            "code_files",
        }
        provided_fields = replacement_fields & self.model_fields_set
        if not provided_fields:
            raise ValueError("at least one draft replacement field must be provided")
        if any(getattr(self, field_name) is None for field_name in provided_fields):
            raise ValueError("draft replacement fields must not be null")
        if self.code_files is not None:
            _validate_unique_experiment_code_file_paths(self.code_files)
        return self


class PromptVersionCreateRequest(ContractModel):
    prompt: LongText


class VersionedRecord(ContractModel):
    id: UUID
    project_id: UUID
    owner_id: UUID
    version: Annotated[int, Field(ge=1)]
    parent_version_id: UUID | None
    created_at: datetime

    @model_validator(mode="after")
    def validate_parent_version(self) -> VersionedRecord:
        if self.version == 1 and self.parent_version_id is not None:
            raise ValueError("first version must not have a parent_version_id")
        if self.version > 1 and self.parent_version_id is None:
            raise ValueError("later versions must have a parent_version_id")
        return self


class ExperimentVersion(VersionedRecord):
    experiment_id: UUID
    draft_revision: Annotated[int, Field(ge=1)]
    model_spec: ModelSpec
    parameters: Annotated[tuple[ExperimentParameter, ...], Field(max_length=200)]
    observables: Annotated[tuple[ExperimentObservable, ...], Field(max_length=200)]
    assumptions: Annotated[tuple[ExperimentAssumption, ...], Field(max_length=100)]
    visualization: JsonObject = Field(default_factory=dict)
    code_files: Annotated[tuple[ExperimentCodeFile, ...], Field(max_length=20)]
    content_hash: Sha256

    @model_validator(mode="after")
    def validate_unique_code_file_paths(self) -> ExperimentVersion:
        _validate_unique_experiment_code_file_paths(self.code_files)
        return self


class ExperimentVersionCreateRequest(ContractModel):
    expected_revision: Annotated[int, Field(ge=1)]


class ExperimentVersionPage(ContractModel):
    items: Annotated[tuple[ExperimentVersion, ...], Field(max_length=100)]
    next_cursor: Annotated[int | None, Field(ge=1)] = None


class ExperimentPatchOperation(ContractModel):
    operation: ExperimentPatchOperationKind
    path: Annotated[str, Field(min_length=1, max_length=500, pattern=r"^/")]
    value: JsonValue = None

    @model_validator(mode="after")
    def validate_value_by_operation(self) -> ExperimentPatchOperation:
        value_provided = "value" in self.model_fields_set
        if self.operation in {
            ExperimentPatchOperationKind.ADD,
            ExperimentPatchOperationKind.REPLACE,
        } and not value_provided:
            raise ValueError("add and replace operations require a value")
        if self.operation is ExperimentPatchOperationKind.REMOVE and value_provided:
            raise ValueError("remove operations must not include a value")
        return self


class ExperimentPatchProposal(ContractModel):
    id: UUID
    experiment_id: UUID
    project_id: UUID
    owner_id: UUID
    expected_revision: Annotated[int, Field(ge=1)]
    status: ExperimentPatchProposalStatus
    operations: Annotated[tuple[ExperimentPatchOperation, ...], Field(min_length=1, max_length=100)]
    assumptions: Annotated[tuple[ExperimentAssumption, ...], Field(max_length=100)]
    source: AssumptionSource
    created_at: datetime
    resolved_at: datetime | None = None

    @model_validator(mode="after")
    def validate_resolution_timestamp(self) -> ExperimentPatchProposal:
        if self.status is ExperimentPatchProposalStatus.PENDING and self.resolved_at is not None:
            raise ValueError("pending proposals must not have a resolved_at timestamp")
        if self.status is not ExperimentPatchProposalStatus.PENDING and self.resolved_at is None:
            raise ValueError("resolved proposals require a resolved_at timestamp")
        return self


class ExperimentPatchProposalPage(ContractModel):
    items: Annotated[tuple[ExperimentPatchProposal, ...], Field(max_length=100)]
    next_cursor: UUID | None = None


class ExperimentPatchProposalApplyRequest(ContractModel):
    expected_revision: Annotated[int, Field(ge=1)]


class ExperimentPatchProposalRejectRequest(ContractModel):
    expected_revision: Annotated[int, Field(ge=1)]
    reason: Annotated[str | None, Field(max_length=2_000)] = None


class PromptVersion(VersionedRecord):
    prompt: LongText


class PromptVersionPage(ContractModel):
    items: Annotated[tuple[PromptVersion, ...], Field(max_length=100)]
    next_cursor: Annotated[int | None, Field(ge=1)] = None


class FormulaStep(ContractModel):
    expression: Annotated[str, Field(min_length=1, max_length=2_000)]
    explanation: Annotated[str, Field(min_length=1, max_length=2_000)]


class ContentPlanScene(ContractModel):
    scene_number: Annotated[int, Field(ge=1, le=24)]
    teaching_goal: Annotated[str, Field(min_length=1, max_length=1_000)]
    formula_steps: Annotated[tuple[FormulaStep, ...], Field(min_length=1, max_length=24)]
    visual_intent: Annotated[str, Field(min_length=1, max_length=2_000)]
    narration_placeholder: Annotated[str, Field(min_length=1, max_length=4_000)]


class ContentPlanVersion(VersionedRecord):
    schema_version: Literal["1.0", "1.1"]
    title: ShortText
    audience: Audience
    language: Language
    target_duration_seconds: Annotated[int, Field(ge=15, le=600)]
    derivation_style: DerivationStyle = DerivationStyle.STEP_BY_STEP
    explicit_assumptions: Annotated[tuple[ShortText, ...], Field(max_length=20)]
    ambiguities: Annotated[tuple[ShortText, ...], Field(max_length=20)] = ()
    scenes: Annotated[tuple[ContentPlanScene, ...], Field(min_length=1, max_length=24)]

    @model_validator(mode="before")
    @classmethod
    def require_phase6_fields(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("schema_version") == "1.1":
            missing = {"derivation_style", "ambiguities"} - set(value)
            if missing:
                raise ValueError(f"ContentPlan 1.1 missing explicit fields: {sorted(missing)}")
        return value


class ContentPlanVersionPage(ContractModel):
    items: Annotated[tuple[ContentPlanVersion, ...], Field(max_length=100)]
    next_cursor: Annotated[int | None, Field(ge=1)] = None


class ContentPlanGenerationRequest(ContractModel):
    project_id: UUID
    owner_id: UUID
    prompt_version_id: UUID
    audience: Audience | None = None
    language: Language = Language.ZH_CN
    target_duration_seconds: Annotated[int | None, Field(ge=30, le=180)] = None
    derivation_style: DerivationStyle | None = None
    explicit_assumptions: Annotated[tuple[ShortText, ...], Field(max_length=20)] = ()


class WorkspaceContentPlanGenerationRequest(ContractModel):
    prompt_version_id: UUID
    audience: Audience | None = None
    language: Language = Language.ZH_CN
    target_duration_seconds: Annotated[int | None, Field(ge=30, le=180)] = None
    derivation_style: DerivationStyle | None = None
    explicit_assumptions: Annotated[tuple[ShortText, ...], Field(max_length=20)] = ()


class ClarificationQuestion(ContractModel):
    field: ClarificationField
    question: Annotated[str, Field(min_length=1, max_length=500)]
    options: Annotated[tuple[ShortText, ...], Field(max_length=6)] = ()


class ContentPlanLimitation(ContractModel):
    code: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")]
    message: Annotated[str, Field(min_length=1, max_length=1_000)]
    supported_alternative: Annotated[str | None, Field(max_length=1_000)] = None


class ContentPlanDraft(ContractModel):
    schema_version: Literal["1.1"]
    title: ShortText
    audience: Audience
    language: Language
    target_duration_seconds: Annotated[int, Field(ge=30, le=180)]
    derivation_style: DerivationStyle
    explicit_assumptions: Annotated[tuple[ShortText, ...], Field(max_length=20)]
    ambiguities: Annotated[tuple[ShortText, ...], Field(max_length=20)]
    scenes: Annotated[tuple[ContentPlanScene, ...], Field(min_length=1, max_length=24)]


class ContentPlanVersionCreateRequest(ContractModel):
    parent_version_id: UUID
    content_plan: ContentPlanDraft


class ContentPlanModelResponse(ContractModel):
    outcome: ContentPlanOutcome
    plan: ContentPlanDraft | None = None
    clarifications: Annotated[tuple[ClarificationQuestion, ...], Field(max_length=4)] = ()
    limitations: Annotated[tuple[ContentPlanLimitation, ...], Field(max_length=4)] = ()

    @model_validator(mode="after")
    def validate_outcome_payload(self) -> ContentPlanModelResponse:
        if self.outcome is ContentPlanOutcome.READY:
            if self.plan is None or self.clarifications or self.limitations:
                raise ValueError("ready requires only plan")
        elif self.outcome is ContentPlanOutcome.NEEDS_CLARIFICATION:
            if self.plan is not None or not self.clarifications or self.limitations:
                raise ValueError("needs_clarification requires only clarifications")
        elif self.plan is not None or self.clarifications or not self.limitations:
            raise ValueError("unsupported requires only limitations")
        return self


class ContentPlanGenerationResponse(ContractModel):
    outcome: ContentPlanOutcome
    content_plan_version: ContentPlanVersion | None = None
    clarifications: Annotated[tuple[ClarificationQuestion, ...], Field(max_length=4)] = ()
    limitations: Annotated[tuple[ContentPlanLimitation, ...], Field(max_length=4)] = ()
    attempts_used: Annotated[int, Field(ge=1, le=2)]


class CodeGenerationRequest(ContractModel):
    project_id: UUID
    owner_id: UUID
    prompt_version_id: UUID
    content_plan_version_id: UUID
    category: CodeGenerationCategory
    force_regenerate: bool = False


class WorkspaceCodeGenerationRequest(ContractModel):
    prompt_version_id: UUID
    content_plan_version_id: UUID
    category: CodeGenerationCategory
    force_regenerate: bool = False


class CodeModelResponse(ContractModel):
    scene_class: Literal["GeneratedScene"]
    code: Annotated[str, Field(min_length=1, max_length=200_000)]
    assumptions: Annotated[tuple[ShortText, ...], Field(max_length=20)] = ()

    @field_validator("code")
    @classmethod
    def reject_markdown_fences(cls, value: str) -> str:
        if "```" in value:
            raise ValueError("code must not contain Markdown fences")
        return value


class CodeVersion(VersionedRecord):
    prompt_version_id: UUID
    content_plan_version_id: UUID
    source_code: Annotated[str, Field(min_length=1, max_length=200_000)]
    source_sha256: Sha256
    scene_class: Annotated[str, Field(pattern=r"^[A-Z][A-Za-z0-9]{1,99}$")]
    engine: Literal["manimce"]
    engine_version: Literal["0.20.1"]
    category: CodeGenerationCategory = CodeGenerationCategory.FORMULA_DERIVATION
    generation_mode: CodeGenerationMode = CodeGenerationMode.FULL
    prompt_template_version: Annotated[str | None, Field(max_length=100)] = None
    provider_model: Annotated[str | None, Field(max_length=100)] = None
    assumptions: Annotated[tuple[ShortText, ...], Field(max_length=20)] = ()


class CodeGenerationResponse(ContractModel):
    outcome: CodeGenerationOutcome
    code_version: CodeVersion | None = None
    attempts_used: Annotated[int, Field(ge=0, le=3)]
    mode: CodeGenerationMode
    error_code: CodeGenerationErrorCode | None = None

    @model_validator(mode="after")
    def validate_outcome_payload(self) -> CodeGenerationResponse:
        successful = self.outcome in {
            CodeGenerationOutcome.READY,
            CodeGenerationOutcome.DEGRADED,
        }
        if successful and (self.code_version is None or self.error_code is not None):
            raise ValueError("ready/degraded requires only code_version")
        if not successful and (self.code_version is not None or self.error_code is None):
            raise ValueError("failed/paused requires only error_code")
        if self.outcome is CodeGenerationOutcome.READY and self.mode is not CodeGenerationMode.FULL:
            raise ValueError("ready requires full generation mode")
        if (
            self.outcome is CodeGenerationOutcome.DEGRADED
            and self.mode is not CodeGenerationMode.DETERMINISTIC_TEMPLATE
        ):
            raise ValueError("degraded requires deterministic template mode")
        return self


class RenderJob(ContractModel):
    id: UUID
    project_id: UUID
    owner_id: UUID
    code_version_id: UUID
    profile: RenderProfile
    status: RenderJobStatus
    idempotency_key: Annotated[str, Field(min_length=16, max_length=128)]
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_code: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    attempt_count: Annotated[int, Field(ge=0)] = 0
    lease_owner: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    lease_token: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    cancellation_requested_at: datetime | None = None
    state_version: Annotated[int, Field(ge=0)] = 0


class RenderJobSubmission(ContractModel):
    project_id: UUID
    owner_id: UUID
    code_version_id: UUID
    profile: RenderProfile
    idempotency_key: Annotated[str, Field(min_length=16, max_length=128)]


class WorkspaceRenderJobSubmission(ContractModel):
    code_version_id: UUID
    profile: RenderProfile
    idempotency_key: Annotated[str, Field(min_length=16, max_length=128)]


class RenderJobLeaseRequest(ContractModel):
    runner_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,99}$")]
    lease_seconds: Annotated[int, Field(ge=5, le=300)] = 30


class RenderJobLease(ContractModel):
    job_id: UUID
    code_version_id: UUID
    content_plan_version_id: UUID
    target_duration_seconds: Annotated[float, Field(gt=0, le=600)]
    profile: RenderProfile
    scene_class: Annotated[str, Field(pattern=r"^[A-Z][A-Za-z0-9]{1,99}$")]
    source_code: Annotated[str, Field(min_length=1, max_length=200_000)]
    source_sha256: Sha256
    lease_token: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    lease_expires_at: datetime
    attempt_number: Annotated[int, Field(ge=1, le=3)]


class RenderJobHeartbeat(ContractModel):
    lease_token: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    extend_seconds: Annotated[int, Field(ge=5, le=300)] = 30


class RenderArtifactPayload(ContractModel):
    kind: ArtifactKind
    relative_path: RelativePath
    sha256: Sha256
    byte_size: Annotated[int, Field(ge=1)]

    @field_validator("relative_path")
    @classmethod
    def validate_relative_artifact_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("relative_path must stay inside the artifact directory")
        return value


class RenderJobCompletion(ContractModel):
    lease_token: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    artifacts: Annotated[tuple[RenderArtifactPayload, ...], Field(min_length=4, max_length=4)]


class RenderJobFailureReport(ContractModel):
    lease_token: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    failure_code: RenderJobFailureCode


class Artifact(ContractModel):
    id: UUID
    project_id: UUID
    owner_id: UUID
    render_job_id: UUID
    kind: ArtifactKind
    relative_path: RelativePath
    sha256: Sha256
    byte_size: Annotated[int, Field(ge=0)]
    created_at: datetime

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("relative_path must stay inside the artifact directory")
        return value


class JobEvent(ContractModel):
    event_id: Annotated[int, Field(ge=1)]
    render_job_id: UUID
    state_version: Annotated[int, Field(ge=0)]
    stage: PipelineStage
    status: RenderJobStatus
    error_code: Annotated[str | None, Field(max_length=100)] = None
    created_at: datetime


class ArtifactDescriptor(ContractModel):
    id: UUID
    render_job_id: UUID
    kind: ArtifactKind
    sha256: Sha256
    byte_size: Annotated[int, Field(ge=0)]
    preview_url: Annotated[str, Field(min_length=1, max_length=500)]
    download_url: Annotated[str, Field(min_length=1, max_length=500)]


class QualityDiagnostic(ContractModel):
    code: QualityDiagnosticCode
    severity: QualitySeverity
    stage: PipelineStage
    message: Annotated[str, Field(min_length=1, max_length=1_000)]
    suggestion: Annotated[str, Field(min_length=1, max_length=1_000)]
    evidence_ref: RelativePath | None = None
    measured_value: float | None = None
    threshold_value: float | None = None

    @field_validator("evidence_ref")
    @classmethod
    def validate_evidence_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("evidence_ref must stay relative")
        return value


class QualityReport(ContractModel):
    id: UUID
    project_id: UUID
    owner_id: UUID
    render_job_id: UUID
    code_version_id: UUID
    content_plan_version_id: UUID
    status: QualityStatus
    target_duration_seconds: Annotated[float, Field(gt=0, le=600)]
    estimated_duration_seconds: Annotated[float | None, Field(ge=0, le=3_600)] = None
    actual_duration_seconds: Annotated[float | None, Field(ge=0, le=3_600)] = None
    frame_rate: Annotated[float | None, Field(gt=0, le=240)] = None
    frame_count: Annotated[int | None, Field(ge=0)] = None
    score: Annotated[int | None, Field(ge=0, le=100)] = None
    repair_count: Annotated[int, Field(ge=0, le=2)]
    diagnostic_signature: Sha256
    provider_model: Annotated[str, Field(min_length=1, max_length=100)]
    prompt_template_version: Annotated[str, Field(min_length=1, max_length=100)]
    content_plan_schema_version: Annotated[str, Field(min_length=1, max_length=20)]
    manim_version: Annotated[str, Field(min_length=1, max_length=50)]
    image_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    ast_policy_version: Annotated[str, Field(min_length=1, max_length=100)]
    diagnostic_policy_version: Annotated[str, Field(min_length=1, max_length=100)]
    created_at: datetime


class QualityReportPage(ContractModel):
    items: Annotated[tuple[QualityReport, ...], Field(max_length=100)]
    next_cursor: UUID | None = None


class QualityHumanRatingRequest(ContractModel):
    score: Annotated[int, Field(ge=0, le=100)]
    notes: Annotated[str | None, Field(max_length=2_000)] = None


class GenerationAttempt(ContractModel):
    id: UUID
    project_id: UUID
    owner_id: UUID
    stage: GenerationStage
    attempt_number: Annotated[int, Field(ge=1, le=3)]
    status: GenerationStatus
    input_version_id: UUID
    output_version_id: UUID | None = None
    error_code: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    provider_request_id: Annotated[str | None, Field(max_length=200)] = None
    provider_model: Annotated[str | None, Field(max_length=100)] = None
    prompt_tokens: Annotated[int | None, Field(ge=0)] = None
    completion_tokens: Annotated[int | None, Field(ge=0)] = None
    candidate_sha256: Sha256 | None = None
    diagnostic_sha256: Sha256 | None = None
    created_at: datetime


CONTRACT_MODELS = (
    User,
    AuthenticatedUser,
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    LogoutResponse,
    ApiErrorDetail,
    ApiErrorResponse,
    Project,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    ProjectPage,
    Experiment,
    ExperimentCreateRequest,
    ExperimentPage,
    ExperimentDraft,
    ExperimentDraftUpdateRequest,
    ExperimentVersion,
    ExperimentVersionCreateRequest,
    ExperimentVersionPage,
    ExperimentPatchProposal,
    ExperimentPatchProposalPage,
    ExperimentPatchProposalApplyRequest,
    ExperimentPatchProposalRejectRequest,
    PromptVersionCreateRequest,
    PromptVersion,
    PromptVersionPage,
    ContentPlanVersion,
    ContentPlanVersionPage,
    ContentPlanVersionCreateRequest,
    ContentPlanGenerationRequest,
    WorkspaceContentPlanGenerationRequest,
    ClarificationQuestion,
    ContentPlanLimitation,
    ContentPlanDraft,
    ContentPlanModelResponse,
    ContentPlanGenerationResponse,
    CodeGenerationRequest,
    WorkspaceCodeGenerationRequest,
    CodeModelResponse,
    CodeVersion,
    CodeGenerationResponse,
    RenderJob,
    RenderJobSubmission,
    WorkspaceRenderJobSubmission,
    RenderJobLeaseRequest,
    RenderJobLease,
    RenderJobHeartbeat,
    RenderArtifactPayload,
    RenderJobCompletion,
    RenderJobFailureReport,
    Artifact,
    ArtifactDescriptor,
    QualityDiagnostic,
    QualityReport,
    QualityReportPage,
    QualityHumanRatingRequest,
    JobEvent,
    GenerationAttempt,
    QualityReport,
)

PROJECT_RECORD_MODELS = (
    Project,
    PromptVersion,
    ContentPlanVersion,
    CodeVersion,
    RenderJob,
    Artifact,
    GenerationAttempt,
)

CONTRACT_ENUMS = (
    Audience,
    Language,
    DerivationStyle,
    ContentPlanOutcome,
    CodeGenerationCategory,
    CodeGenerationMode,
    CodeGenerationOutcome,
    CodeGenerationErrorCode,
    ClarificationField,
    RenderProfile,
    RenderJobStatus,
    RenderJobFailureCode,
    ArtifactKind,
    GenerationStage,
    GenerationStatus,
    QualityStatus,
    QualitySeverity,
    QualityDiagnosticCode,
    ExperimentDomainKind,
    AssumptionSource,
    AssumptionStatus,
    ExperimentPatchProposalStatus,
    ExperimentPatchOperationKind,
)

RENDER_JOB_TRANSITIONS: dict[RenderJobStatus, frozenset[RenderJobStatus]] = {
    RenderJobStatus.QUEUED: frozenset({RenderJobStatus.CLAIMED, RenderJobStatus.CANCELLED}),
    RenderJobStatus.CLAIMED: frozenset(
        {RenderJobStatus.RUNNING, RenderJobStatus.QUEUED, RenderJobStatus.CANCELLED}
    ),
    RenderJobStatus.RUNNING: frozenset(
        {
            RenderJobStatus.SUCCEEDED,
            RenderJobStatus.FAILED,
            RenderJobStatus.QUEUED,
            RenderJobStatus.CANCELLED,
        }
    ),
    RenderJobStatus.SUCCEEDED: frozenset(),
    RenderJobStatus.FAILED: frozenset(),
    RenderJobStatus.CANCELLED: frozenset(),
}


def can_transition_render_job(current: RenderJobStatus, target: RenderJobStatus) -> bool:
    return target in RENDER_JOB_TRANSITIONS[current]
