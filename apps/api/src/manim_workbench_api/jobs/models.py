from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from manim_workbench_contracts import RenderJobStatus, RenderProfile
from pydantic import BaseModel, ConfigDict, Field


class JobResponse(BaseModel):
    """Public Job view: deliberately excludes lease tokens and owner internals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    project_id: UUID
    owner_id: UUID
    code_version_id: UUID
    profile: RenderProfile
    status: RenderJobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_code: str | None = None
    attempt_count: Annotated[int, Field(ge=0)]
    cancellation_requested_at: datetime | None = None
    state_version: Annotated[int, Field(ge=0)]


class LeaseActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lease_token: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class RecoverableJobsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    jobs: tuple[JobResponse, ...]
