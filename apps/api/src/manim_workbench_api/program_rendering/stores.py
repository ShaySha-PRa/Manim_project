"""Persist each compiled segment as an immutable CodeVersion for existing RenderJobs."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from uuid import UUID

from manim_workbench_contracts import (
    CodeGenerationMode,
    CodeGenerationRequest,
    CodeModelResponse,
    ProgramRenderSegment,
)

from manim_workbench_api.code_generation.repository import CodeGenerationRepository

from .service import (
    PROGRAM_RENDERER_VERSION,
    ProgramRenderRequest,
    StagedProgramSegment,
)


class CodeVersionProgramSegmentStore:
    def __init__(
        self,
        repository: CodeGenerationRepository,
        code_request: CodeGenerationRequest,
        *,
        assumptions: tuple[str, ...] = (),
        attach_job: Callable[[int, UUID], None] | None = None,
    ) -> None:
        self._repository = repository
        self._code_request = code_request
        self._assumptions = assumptions
        self._attach_job = attach_job

    def stage(
        self,
        request: ProgramRenderRequest,
        *,
        segment_index: int,
        concat_group_id: UUID,
    ) -> StagedProgramSegment:
        del concat_group_id
        if (
            request.owner_id != self._code_request.owner_id
            or request.project_id != self._code_request.project_id
        ):
            raise ValueError("program identity does not match code generation request")
        segment = request.program.segments[segment_index]
        source_digest = sha256(segment.source.encode("utf-8")).hexdigest()
        template_version = (
            f"{PROGRAM_RENDERER_VERSION}:{request.program_sha256[:32]}:{segment_index}"
        )
        version = self._repository.find_compiled_segment(
            self._code_request,
            source_sha256=source_digest,
            prompt_template_version=template_version,
        )
        if version is None:
            version = self._repository.save_success(
                self._code_request,
                response=CodeModelResponse(
                    scene_class="GeneratedScene",
                    code=segment.source,
                    assumptions=self._assumptions,
                ),
                attempt_number=1,
                mode=CodeGenerationMode.COMPILED_IR,
                prompt_template_version=template_version,
                provider_model=None,
            )
        if version.source_sha256 != source_digest:
            raise ValueError("stored segment source hash does not match compiled source")
        return StagedProgramSegment(
            code_version_id=version.id,
            source_sha256=version.source_sha256,
        )

    def attach_job(self, segment_index: int, render_job_id: UUID) -> None:
        if self._attach_job is not None:
            self._attach_job(segment_index, render_job_id)


class TypedProgramSegmentStore:
    """Stage already-persisted scientific/public compiler segments without fake code versions."""

    def __init__(
        self,
        segments: tuple[ProgramRenderSegment, ...],
        attach_job: Callable[[int, UUID], None],
    ) -> None:
        self._segments = segments
        self._attach_job = attach_job

    def stage(
        self,
        request: ProgramRenderRequest,
        *,
        segment_index: int,
        concat_group_id: UUID,
    ) -> StagedProgramSegment:
        del concat_group_id
        if segment_index >= len(self._segments):
            raise ValueError("persisted program segment is missing")
        persisted = self._segments[segment_index]
        source = request.program.segments[segment_index].source
        source_digest = sha256(source.encode("utf-8")).hexdigest()
        if (
            persisted.segment_index != segment_index
            or persisted.source_sha256 != source_digest
        ):
            raise ValueError("persisted program segment does not match compiled source")
        return StagedProgramSegment(
            source_sha256=persisted.source_sha256,
            program_render_segment_id=persisted.id,
        )

    def attach_job(self, segment_index: int, render_job_id: UUID) -> None:
        self._attach_job(segment_index, render_job_id)
