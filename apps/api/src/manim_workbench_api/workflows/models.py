from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from manim_workbench_contracts import (
    DirectorDraft,
    DirectorPlanRequest,
    GlobalBrief,
    RenderProfile,
    SceneBlockVersion,
    ScenePipelineMode,
    WorkflowEdge,
    WorkflowNode,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorkflowApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VideoWorkflowRecord(WorkflowApiModel):
    id: UUID
    project_id: UUID
    owner_id: UUID
    created_at: datetime


class SceneBlockRecord(WorkflowApiModel):
    id: UUID
    workflow_id: UUID
    project_id: UUID
    owner_id: UUID
    created_at: datetime


class SceneBlockCreation(WorkflowApiModel):
    block: SceneBlockRecord
    version: SceneBlockVersion


class SceneBlockVersionDetail(WorkflowApiModel):
    block_id: UUID
    version: SceneBlockVersion


class SceneBlockCreateRequest(WorkflowApiModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    prompt: Annotated[str, Field(min_length=1, max_length=20_000)]
    pipeline_mode: ScenePipelineMode = ScenePipelineMode.AUTO
    target_duration_seconds: Annotated[int, Field(ge=15, le=120)]
    asset_version_ids: Annotated[tuple[UUID, ...], Field(max_length=16)] = ()


class SceneBlockVersionCreateRequest(SceneBlockCreateRequest):
    parent_version_id: UUID


class WorkflowVersionCreateRequest(WorkflowApiModel):
    parent_version_id: UUID | None = None
    global_brief: GlobalBrief
    nodes: Annotated[tuple[WorkflowNode, ...], Field(min_length=4, max_length=10)]
    edges: Annotated[tuple[WorkflowEdge, ...], Field(min_length=3, max_length=9)]


class SceneRunCreateRequest(WorkflowApiModel):
    workflow_version_id: UUID
    profile: RenderProfile
    idempotency_key: Annotated[str, Field(min_length=16, max_length=128)]


class ScientificCsvAssetCreateRequest(WorkflowApiModel):
    csv_text: Annotated[str, Field(min_length=1, max_length=200_000)]


class ScientificAssetRecord(WorkflowApiModel):
    id: UUID
    project_id: UUID
    owner_id: UUID
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    mime: str
    size_bytes: Annotated[int, Field(gt=0, le=200_000)]


class CompositionRunCreateRequest(WorkflowApiModel):
    profile: RenderProfile
    idempotency_key: Annotated[str, Field(min_length=16, max_length=128)]


class WorkflowTaskSubmissionResponse(WorkflowApiModel):
    run_id: UUID
    task_id: UUID
    status: str

    @model_validator(mode="after")
    def require_queued(self) -> WorkflowTaskSubmissionResponse:
        if self.status != "queued":
            raise ValueError("new workflow tasks must be queued")
        return self


class DirectorPlanCreateRequest(WorkflowApiModel):
    objective: Annotated[str, Field(min_length=1, max_length=20_000)]
    title: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    language: str
    target_duration_seconds: Annotated[int, Field(ge=30, le=600)]
    style_preset: str | None = None
    asset_version_ids: Annotated[tuple[UUID, ...], Field(max_length=16)] = ()
    idempotency_key: Annotated[str, Field(min_length=16, max_length=128)]

    def to_contract(self, project_id: UUID) -> DirectorPlanRequest:
        return DirectorPlanRequest(project_id=project_id, **self.model_dump())


class DirectorPlanApplyRequest(WorkflowApiModel):
    draft: DirectorDraft
    scene_asset_version_ids: Annotated[
        tuple[Annotated[tuple[UUID, ...], Field(max_length=16)], ...],
        Field(min_length=2, max_length=8),
    ]
    idempotency_key: Annotated[str, Field(min_length=16, max_length=128)]
