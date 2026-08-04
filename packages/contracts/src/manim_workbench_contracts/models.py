from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_SCHEMA_VERSION = "1.1"

ShortText = Annotated[str, Field(min_length=1, max_length=200)]
LongText = Annotated[str, Field(min_length=1, max_length=20_000)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
RelativePath = Annotated[str, Field(min_length=1, max_length=500)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)


class Audience(str, Enum):
    PRIMARY_SCHOOL = "primary_school"
    MIDDLE_SCHOOL = "middle_school"
    HIGH_SCHOOL = "high_school"
    UNDERGRADUATE = "undergraduate"


class Language(str, Enum):
    ZH_CN = "zh-CN"
    EN_US = "en-US"


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


class User(ContractModel):
    id: UUID
    email: Annotated[str, Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")]
    created_at: datetime


class Project(ContractModel):
    id: UUID
    owner_id: UUID
    title: ShortText
    created_at: datetime
    archived_at: datetime | None = None


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


class PromptVersion(VersionedRecord):
    prompt: LongText


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
    schema_version: Literal["1.0"]
    title: ShortText
    audience: Audience
    language: Language
    target_duration_seconds: Annotated[int, Field(ge=15, le=600)]
    explicit_assumptions: Annotated[tuple[ShortText, ...], Field(max_length=20)]
    scenes: Annotated[tuple[ContentPlanScene, ...], Field(min_length=1, max_length=24)]


class CodeVersion(VersionedRecord):
    prompt_version_id: UUID
    content_plan_version_id: UUID
    source_code: Annotated[str, Field(min_length=1, max_length=200_000)]
    source_sha256: Sha256
    engine: Literal["manimce"]
    engine_version: Literal["0.20.1"]


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


class RenderJobLeaseRequest(ContractModel):
    runner_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,99}$")]
    lease_seconds: Annotated[int, Field(ge=5, le=300)] = 30


class RenderJobLease(ContractModel):
    job_id: UUID
    code_version_id: UUID
    profile: RenderProfile
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
    created_at: datetime


CONTRACT_MODELS = (
    User,
    Project,
    PromptVersion,
    ContentPlanVersion,
    CodeVersion,
    RenderJob,
    RenderJobSubmission,
    RenderJobLeaseRequest,
    RenderJobLease,
    RenderJobHeartbeat,
    RenderArtifactPayload,
    RenderJobCompletion,
    RenderJobFailureReport,
    Artifact,
    GenerationAttempt,
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
    RenderProfile,
    RenderJobStatus,
    RenderJobFailureCode,
    ArtifactKind,
    GenerationStage,
    GenerationStatus,
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
