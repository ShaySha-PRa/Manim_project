"""Strict immutable contracts for the linear composable-scene workflow MVP."""

from __future__ import annotations

import math
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from .models import ContractModel, Language, LongText, RenderProfile, Sha256, ShortText


class WorkflowStylePreset(str, Enum):
    DARK_SCIENTIFIC = "dark_scientific"
    LIGHT_ACADEMIC = "light_academic"
    MINIMAL_MATH = "minimal_math"
    PRESENTATION = "presentation"


class ScenePipelineMode(str, Enum):
    AUTO = "auto"
    TEACHING = "teaching"
    SCIENTIFIC = "scientific"


class ScenePipeline(str, Enum):
    TEACHING = "teaching"
    SCIENTIFIC = "scientific"


class SceneBlockRunStatus(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    NEEDS_CONFIRMATION = "needs_confirmation"
    ASSET_REQUIRED = "asset_required"
    COMPILING = "compiling"
    RENDERING = "rendering"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WorkflowNodeKind(str, Enum):
    SCENE = "scene"
    COMPOSE = "compose"
    EXPORT = "export"


class CompositionRunStatus(str, Enum):
    QUEUED = "queued"
    COMPOSING = "composing"
    NOT_READY = "not_ready_to_compose"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ProgramRenderRunStatus(str, Enum):
    COMPILING = "compiling"
    RENDERING = "rendering"
    COMPOSING = "composing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ProgramRenderSegmentStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RENDERING = "rendering"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class GlobalBrief(ContractModel):
    title: ShortText
    language: Language
    target_duration_seconds: Annotated[int, Field(ge=30, le=600)]
    aspect_ratio: Literal["16:9"] = "16:9"
    style_preset: WorkflowStylePreset
    background: Annotated[str, Field(min_length=1, max_length=40)]
    palette: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=40)], ...],
        Field(min_length=1, max_length=8),
    ]
    notation: Annotated[dict[str, str], Field(max_length=32)] = Field(default_factory=dict)
    scientific_parameters: Annotated[dict[str, float], Field(max_length=32)] = Field(
        default_factory=dict
    )

    @field_validator("notation")
    @classmethod
    def validate_notation(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not 1 <= len(key) <= 80 or not 1 <= len(item) <= 200 for key, item in value.items()):
            raise ValueError("notation keys and values must be bounded non-empty strings")
        return value

    @field_validator("scientific_parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not 1 <= len(key) <= 80 for key in value):
            raise ValueError("scientific parameter names must be bounded")
        if any(not math.isfinite(item) for item in value.values()):
            raise ValueError("scientific parameters must be finite")
        return value


class SceneBlockVersion(ContractModel):
    id: UUID
    project_id: UUID
    workflow_id: UUID
    owner_id: UUID
    version: Annotated[int, Field(ge=1)]
    parent_version_id: UUID | None
    title: ShortText
    prompt: LongText
    pipeline_mode: ScenePipelineMode
    target_duration_seconds: Annotated[int, Field(ge=15, le=120)]
    asset_version_ids: Annotated[tuple[UUID, ...], Field(max_length=16)] = ()
    created_at: datetime

    @model_validator(mode="after")
    def validate_parent(self) -> SceneBlockVersion:
        if self.version == 1 and self.parent_version_id is not None:
            raise ValueError("first version cannot have a parent_version_id")
        if self.version > 1 and self.parent_version_id is None:
            raise ValueError("later versions require a parent_version_id")
        if len(set(self.asset_version_ids)) != len(self.asset_version_ids):
            raise ValueError("asset_version_ids must be unique")
        return self


class SceneBlockRun(ContractModel):
    id: UUID
    project_id: UUID
    owner_id: UUID
    scene_block_version_id: UUID
    profile: RenderProfile
    status: SceneBlockRunStatus
    pipeline_used: ScenePipeline | None = None
    intent_ref: UUID | None = None
    animation_ir_ref: UUID | None = None
    compiled_program_ref: UUID | None = None
    preview_artifact_id: UUID | None = None
    final_artifact_id: UUID | None = None
    cache_key: Sha256
    error_code: Annotated[str | None, Field(pattern=r"^[a-z][a-z0-9_]{1,99}$")] = None
    state_version: Annotated[int, Field(ge=0)] = 0
    created_at: datetime

    @model_validator(mode="after")
    def validate_terminal_payload(self) -> SceneBlockRun:
        if self.status is SceneBlockRunStatus.SUCCEEDED:
            if self.pipeline_used is None or (
                self.preview_artifact_id is None and self.final_artifact_id is None
            ):
                raise ValueError("succeeded run requires pipeline and an artifact")
            if self.error_code is not None:
                raise ValueError("succeeded run cannot carry an error_code")
        elif self.status in {
            SceneBlockRunStatus.FAILED,
            SceneBlockRunStatus.NEEDS_CONFIRMATION,
            SceneBlockRunStatus.ASSET_REQUIRED,
        }:
            if self.error_code is None:
                raise ValueError("stopped run requires an error_code")
            if self.preview_artifact_id is not None or self.final_artifact_id is not None:
                raise ValueError("stopped run cannot publish an artifact")
        elif self.error_code is not None:
            raise ValueError("active run cannot carry an error_code")
        return self


class ProgramRenderRun(ContractModel):
    id: UUID
    scene_block_run_id: UUID
    project_id: UUID
    owner_id: UUID
    profile: RenderProfile
    program_sha256: Sha256
    quality_policy: Literal["teaching", "scientific"]
    status: ProgramRenderRunStatus
    segment_count: Annotated[int, Field(ge=1, le=32)]
    failure_code: Annotated[str | None, Field(pattern=r"^[a-z][a-z0-9_]{1,99}$")] = None
    created_at: datetime


class ProgramRenderSegment(ContractModel):
    id: UUID
    program_render_run_id: UUID
    segment_index: Annotated[int, Field(ge=0, le=31)]
    source_sha256: Sha256
    scene_class: Annotated[str, Field(pattern=r"^[A-Z][A-Za-z0-9]{1,99}$")]
    target_duration_seconds: Annotated[float, Field(gt=0, le=600)]
    render_job_id: UUID | None = None
    input_artifact_id: UUID | None = None
    input_artifact_sha256: Sha256 | None = None
    status: ProgramRenderSegmentStatus
    failure_code: Annotated[str | None, Field(pattern=r"^[a-z][a-z0-9_]{1,99}$")] = None


class WorkflowArtifact(ContractModel):
    id: UUID
    project_id: UUID
    owner_id: UUID
    scene_block_run_id: UUID | None = None
    composition_run_id: UUID | None = None
    profile: RenderProfile
    relative_path: Annotated[str, Field(min_length=1, max_length=500)]
    sha256: Sha256
    byte_size: Annotated[int, Field(gt=0)]
    duration_seconds: Annotated[float, Field(gt=0, le=600)]
    media_type: Literal["video/mp4"] = "video/mp4"
    created_at: datetime

    @model_validator(mode="after")
    def validate_single_source(self) -> WorkflowArtifact:
        if (self.scene_block_run_id is None) == (self.composition_run_id is None):
            raise ValueError("workflow artifact requires exactly one run source")
        return self


class WorkflowNode(ContractModel):
    id: UUID
    kind: WorkflowNodeKind
    scene_block_version_id: UUID | None = None

    @model_validator(mode="after")
    def validate_reference(self) -> WorkflowNode:
        if self.kind is WorkflowNodeKind.SCENE and self.scene_block_version_id is None:
            raise ValueError("scene node requires scene_block_version_id")
        if self.kind is not WorkflowNodeKind.SCENE and self.scene_block_version_id is not None:
            raise ValueError("non-scene node cannot reference a scene block")
        return self


class WorkflowEdge(ContractModel):
    source_node_id: UUID
    target_node_id: UUID

    @model_validator(mode="after")
    def reject_self_edge(self) -> WorkflowEdge:
        if self.source_node_id == self.target_node_id:
            raise ValueError("workflow edge cannot target itself")
        return self


class VideoWorkflowVersion(ContractModel):
    id: UUID
    workflow_id: UUID
    project_id: UUID
    owner_id: UUID
    version: Annotated[int, Field(ge=1)]
    parent_version_id: UUID | None
    global_brief: GlobalBrief
    nodes: Annotated[tuple[WorkflowNode, ...], Field(min_length=4, max_length=10)]
    edges: Annotated[tuple[WorkflowEdge, ...], Field(min_length=3, max_length=9)]
    created_at: datetime

    @model_validator(mode="after")
    def validate_version_shape(self) -> VideoWorkflowVersion:
        if self.version == 1 and self.parent_version_id is not None:
            raise ValueError("first version cannot have a parent_version_id")
        if self.version > 1 and self.parent_version_id is None:
            raise ValueError("later versions require a parent_version_id")
        scene_count = sum(node.kind is WorkflowNodeKind.SCENE for node in self.nodes)
        if not 2 <= scene_count <= 8:
            raise ValueError("workflow must contain 2 to 8 scene nodes")
        if sum(node.kind is WorkflowNodeKind.COMPOSE for node in self.nodes) != 1:
            raise ValueError("workflow must contain exactly one compose node")
        if sum(node.kind is WorkflowNodeKind.EXPORT for node in self.nodes) != 1:
            raise ValueError("workflow must contain exactly one export node")
        if len({node.id for node in self.nodes}) != len(self.nodes):
            raise ValueError("workflow node ids must be unique")
        return self


class CompositionManifestClip(ContractModel):
    scene_block_version_id: UUID
    intent_ref: UUID | None = None
    animation_ir_ref: UUID | None = None
    compiled_program_ref: UUID | None = None
    artifact_sha256: Sha256
    duration_seconds: Annotated[float, Field(gt=0, le=120)]
    position: Annotated[int, Field(ge=1, le=8)]


class CompositionManifest(ContractModel):
    workflow_version_id: UUID
    profile: RenderProfile
    clips: Annotated[
        tuple[CompositionManifestClip, ...], Field(min_length=2, max_length=8)
    ]
    total_duration_seconds: Annotated[float, Field(gt=0, le=600)]
    composer_version: Annotated[str, Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def validate_clip_order_and_duration(self) -> CompositionManifest:
        if tuple(item.position for item in self.clips) != tuple(range(1, len(self.clips) + 1)):
            raise ValueError("manifest clip positions must be contiguous and ordered")
        if abs(sum(item.duration_seconds for item in self.clips) - self.total_duration_seconds) > 1:
            raise ValueError("manifest total duration must match clip durations")
        return self


class CompositionRun(ContractModel):
    id: UUID
    workflow_version_id: UUID
    project_id: UUID
    owner_id: UUID
    profile: RenderProfile
    status: CompositionRunStatus
    cache_key: Sha256
    manifest: CompositionManifest | None = None
    artifact_id: UUID | None = None
    error_code: Annotated[str | None, Field(pattern=r"^[a-z][a-z0-9_]{1,99}$")] = None
    state_version: Annotated[int, Field(ge=0)] = 0
    created_at: datetime

    @model_validator(mode="after")
    def validate_terminal_payload(self) -> CompositionRun:
        if self.status is CompositionRunStatus.SUCCEEDED:
            if self.manifest is None or self.artifact_id is None or self.error_code is not None:
                raise ValueError("succeeded composition requires manifest and artifact")
        elif self.status in {CompositionRunStatus.FAILED, CompositionRunStatus.NOT_READY}:
            if self.error_code is None or self.artifact_id is not None:
                raise ValueError("stopped composition requires only error_code")
        elif (
            self.manifest is not None
            or self.artifact_id is not None
            or self.error_code is not None
        ):
            raise ValueError("active composition cannot expose terminal output")
        return self
