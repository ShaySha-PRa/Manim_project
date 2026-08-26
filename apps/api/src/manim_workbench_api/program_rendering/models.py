"""Immutable contracts for rendering a complete CompiledProgram."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from manim_workbench_contracts import RenderProfile

from manim_workbench_api.compiler.base import CompiledProgram


class ProgramQualityPolicy(str, Enum):
    TEACHING = "teaching"
    SCIENTIFIC = "scientific"


class ProgramRenderStatus(str, Enum):
    QUEUED = "queued"
    RENDERING = "rendering"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ProgramRenderRequest:
    owner_id: UUID
    project_id: UUID
    program: CompiledProgram
    program_sha256: str
    profile: RenderProfile
    idempotency_key: str
    deadline_seconds: int
    quality_policy: ProgramQualityPolicy

    def __post_init__(self) -> None:
        if not self.program.segments:
            raise ValueError("program must contain at least one segment")
        if len(self.program_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.program_sha256
        ):
            raise ValueError("program_sha256 must be lowercase SHA-256")
        if len(self.idempotency_key) != 64 or any(
            character not in "0123456789abcdef" for character in self.idempotency_key
        ):
            raise ValueError("idempotency_key must be lowercase SHA-256")
        if not 5 <= self.deadline_seconds <= 3_600:
            raise ValueError("deadline_seconds must be in the range [5, 3600]")


@dataclass(frozen=True, slots=True)
class RenderedSegment:
    segment_index: int
    source_sha256: str
    status: ProgramRenderStatus
    render_job_id: UUID | None = None
    artifact_id: UUID | None = None
    artifact_sha256: str | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if self.segment_index < 0:
            raise ValueError("segment_index must be non-negative")
        if len(self.source_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.source_sha256
        ):
            raise ValueError("source_sha256 must be lowercase SHA-256")
        if self.status is ProgramRenderStatus.SUCCEEDED:
            if (
                self.artifact_id is None
                or self.artifact_sha256 is None
                or self.failure_code is not None
            ):
                raise ValueError("succeeded segment requires artifact identity")
            if len(self.artifact_sha256) != 64 or any(
                character not in "0123456789abcdef" for character in self.artifact_sha256
            ):
                raise ValueError("artifact_sha256 must be lowercase SHA-256")
        elif self.status is ProgramRenderStatus.FAILED:
            if (
                not self.failure_code
                or self.artifact_id is not None
                or self.artifact_sha256 is not None
            ):
                raise ValueError("failed segment requires only failure_code")
        elif (
            self.artifact_id is not None
            or self.artifact_sha256 is not None
            or self.failure_code is not None
        ):
            raise ValueError("active segment cannot expose artifact or failure")


@dataclass(frozen=True, slots=True)
class RenderedProgram:
    program_sha256: str
    profile: RenderProfile
    status: ProgramRenderStatus
    segments: tuple[RenderedSegment, ...]
    artifact_id: UUID | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if len(self.program_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.program_sha256
        ):
            raise ValueError("program_sha256 must be lowercase SHA-256")
        indexes = tuple(segment.segment_index for segment in self.segments)
        if indexes != tuple(range(len(self.segments))):
            raise ValueError("rendered segments must be contiguous and ordered")
        if self.status is ProgramRenderStatus.SUCCEEDED:
            if self.artifact_id is None or self.failure_code is not None:
                raise ValueError("succeeded program requires only artifact_id")
            if not self.segments or any(
                segment.status is not ProgramRenderStatus.SUCCEEDED for segment in self.segments
            ):
                raise ValueError("succeeded program requires every segment to succeed")
        elif self.status is ProgramRenderStatus.FAILED:
            if not self.failure_code or self.artifact_id is not None:
                raise ValueError("failed program requires only failure_code")
        elif self.artifact_id is not None or self.failure_code is not None:
            raise ValueError("active program cannot expose artifact or failure")
