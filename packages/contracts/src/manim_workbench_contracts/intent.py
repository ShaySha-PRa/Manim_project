"""IntentSpec, ToolRun, and Animation Agent request/response contracts."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from .animation_ir import AnimationIR
from .models import (
    Audience,
    CodeGenerationCategory,
    CodeVersion,
    ContentPlanVersion,
    ContractModel,
    Language,
    LongText,
    PromptVersion,
    Sha256,
    ShortText,
)

IntentId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.]{0,63}$")]


class AgentRunOutcome(str, Enum):
    READY = "ready"
    NEEDS_CONFIRMATION = "needs_confirmation"
    ASSET_REQUIRED = "asset_required"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class IntentDomain(str, Enum):
    PHYSICS_WAVE = "physics.wave"
    MATH_SIGNAL = "math.signal"
    DYNAMICAL_SYSTEMS = "dynamical_systems"
    CONTROL = "control"
    DATA_ANALYSIS = "data_analysis"
    GEOMETRY_DIFF3D = "geometry.diff3d"
    SCIENTIFIC_REPRODUCTION = "scientific_reproduction"
    TEACHING = "teaching"


class ToolOp(str, Enum):
    WAVE2D_SUPERPOSITION = "wave2d_superposition"
    FOURIER_SQUARE_WAVE = "fourier_square_wave"
    LORENZ_ENSEMBLE = "lorenz_ensemble"
    PID_STEP_RESPONSE = "pid_step_response"
    CSV_ANOMALY = "csv_anomaly"
    FRENET_FRAME = "frenet_frame"


class ToolNeed(ContractModel):
    op: ToolOp
    params: Annotated[dict[str, float | int | str | bool], Field(max_length=32)] = {}


class IntentSpec(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    domain: IntentDomain
    goal: Annotated[str, Field(min_length=1, max_length=1_000)]
    assumptions: Annotated[tuple[ShortText, ...], Field(max_length=20)] = ()
    tools_needed: Annotated[tuple[ToolNeed, ...], Field(max_length=8)] = ()
    output_duration_seconds: Annotated[float, Field(gt=0, le=180)] = 12.0
    dimension: Literal["2d", "3d"] = "2d"
    needs_confirmation: bool = False
    asset_required: bool = False
    asset_kind: Annotated[str | None, Field(max_length=40)] = None
    category_hint: CodeGenerationCategory = CodeGenerationCategory.FUNCTION_VISUALIZATION

    @model_validator(mode="after")
    def validate_asset_flags(self) -> IntentSpec:
        if self.asset_required and self.asset_kind is None:
            raise ValueError("asset_required requires asset_kind")
        return self


class ToolRun(ContractModel):
    id: IntentId
    op: ToolOp
    params_sha256: Sha256
    input_sha256: Sha256
    output_sha256: Sha256
    artifact_ref: Annotated[str, Field(min_length=1, max_length=200)]
    artifact_path: Annotated[str, Field(min_length=1, max_length=500)]
    assertions: Annotated[dict[str, float | int | bool | str], Field(max_length=32)] = {}


class AgentEvent(ContractModel):
    stage: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
    status: Literal["started", "succeeded", "failed", "skipped"]
    message: Annotated[str, Field(min_length=1, max_length=1_000)]


class WorkspaceAgentRunRequest(ContractModel):
    prompt: LongText
    audience: Audience = Audience.UNDERGRADUATE
    language: Language = Language.ZH_CN
    target_duration_seconds: Annotated[int, Field(ge=30, le=180)] = 60
    csv_text: Annotated[str | None, Field(max_length=200_000)] = None


class AgentRunRequest(WorkspaceAgentRunRequest):
    project_id: UUID
    owner_id: UUID


class AgentRunResponse(ContractModel):
    outcome: AgentRunOutcome
    intent: IntentSpec | None = None
    tool_runs: Annotated[tuple[ToolRun, ...], Field(max_length=8)] = ()
    animation_ir: AnimationIR | None = None
    events: Annotated[tuple[AgentEvent, ...], Field(max_length=32)] = ()
    prompt_version: PromptVersion | None = None
    content_plan_version: ContentPlanVersion | None = None
    code_version: CodeVersion | None = None
    error_code: Annotated[str | None, Field(max_length=100)] = None
    message: Annotated[str | None, Field(max_length=1_000)] = None
