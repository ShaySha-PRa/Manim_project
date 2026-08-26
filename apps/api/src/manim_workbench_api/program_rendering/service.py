"""Submit complete compiler programs to a program-aware rendering backend."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from manim_workbench_contracts import RenderJobStatus, RenderJobSubmission, RenderProfile

from manim_workbench_api.compiler.base import CompiledProgram
from manim_workbench_api.jobs.models import JobResponse

from .models import (
    ProgramQualityPolicy,
    ProgramRenderRequest,
    ProgramRenderStatus,
    RenderedProgram,
    RenderedSegment,
)

PROGRAM_RENDERER_VERSION = "program-render-v1"


class ProgramRenderBackend(Protocol):
    def submit(self, request: ProgramRenderRequest) -> RenderedProgram: ...


@dataclass(frozen=True, slots=True)
class StagedProgramSegment:
    source_sha256: str
    code_version_id: UUID | None = None
    program_render_segment_id: UUID | None = None

    def __post_init__(self) -> None:
        if (self.code_version_id is None) == (self.program_render_segment_id is None):
            raise ValueError("staged segment requires exactly one typed source")


class ProgramSegmentStore(Protocol):
    def stage(
        self,
        request: ProgramRenderRequest,
        *,
        segment_index: int,
        concat_group_id: UUID,
    ) -> StagedProgramSegment: ...

    def attach_job(self, segment_index: int, render_job_id: UUID) -> None: ...


class ProgramJobSubmitter(Protocol):
    def submit(self, submission: RenderJobSubmission) -> tuple[JobResponse, bool]: ...


class JobProgramRenderBackend:
    """Stage every source independently and submit one existing RenderJob per segment."""

    def __init__(self, segment_store: ProgramSegmentStore, jobs: ProgramJobSubmitter) -> None:
        self._segment_store = segment_store
        self._jobs = jobs

    def submit(self, request: ProgramRenderRequest) -> RenderedProgram:
        concat_group_id = uuid5(NAMESPACE_URL, f"program-render:{request.idempotency_key}")
        rendered_segments: list[RenderedSegment] = []
        for index, segment in enumerate(request.program.segments):
            staged = self._segment_store.stage(
                request,
                segment_index=index,
                concat_group_id=concat_group_id,
            )
            source_digest = sha256(segment.source.encode("utf-8")).hexdigest()
            if staged.source_sha256 != source_digest:
                raise ValueError("staged segment source hash does not match compiled source")
            job, _created = self._jobs.submit(
                RenderJobSubmission(
                    project_id=request.project_id,
                    owner_id=request.owner_id,
                    code_version_id=staged.code_version_id,
                    program_render_segment_id=staged.program_render_segment_id,
                    profile=request.profile,
                    idempotency_key=_segment_idempotency_key(request.idempotency_key, index),
                    concat_group_id=concat_group_id,
                    segment_index=index,
                )
            )
            self._segment_store.attach_job(index, job.id)
            rendered_segments.append(_rendered_segment(job, staged.source_sha256))
        segments = tuple(rendered_segments)
        failed = next(
            (segment for segment in segments if segment.status is ProgramRenderStatus.FAILED),
            None,
        )
        if failed is not None:
            return RenderedProgram(
                program_sha256=request.program_sha256,
                profile=request.profile,
                status=ProgramRenderStatus.FAILED,
                segments=segments,
                failure_code="segment_failed",
            )
        status = (
            ProgramRenderStatus.QUEUED
            if all(segment.status is ProgramRenderStatus.QUEUED for segment in segments)
            else ProgramRenderStatus.RENDERING
        )
        return RenderedProgram(
            program_sha256=request.program_sha256,
            profile=request.profile,
            status=status,
            segments=segments,
        )


class ProgramRenderService:
    def __init__(
        self,
        backend: ProgramRenderBackend,
        *,
        owner_id: UUID,
        project_id: UUID,
        idempotency_seed: str,
        deadline_seconds: int,
        quality_policy: ProgramQualityPolicy,
    ) -> None:
        if not 16 <= len(idempotency_seed) <= 128:
            raise ValueError("idempotency_seed length must be in the range [16, 128]")
        if not 5 <= deadline_seconds <= 3_600:
            raise ValueError("deadline_seconds must be in the range [5, 3600]")
        self._backend = backend
        self._owner_id = owner_id
        self._project_id = project_id
        self._idempotency_seed = idempotency_seed
        self._deadline_seconds = deadline_seconds
        self._quality_policy = quality_policy

    def render_program(
        self,
        program: CompiledProgram,
        profile: RenderProfile,
    ) -> RenderedProgram:
        digest = program_sha256(program)
        request = ProgramRenderRequest(
            owner_id=self._owner_id,
            project_id=self._project_id,
            program=program,
            program_sha256=digest,
            profile=profile,
            idempotency_key=_idempotency_key(
                seed=self._idempotency_seed,
                program_digest=digest,
                profile=profile,
                quality_policy=self._quality_policy,
            ),
            deadline_seconds=self._deadline_seconds,
            quality_policy=self._quality_policy,
        )
        rendered = self._backend.submit(request)
        if rendered.program_sha256 != digest or rendered.profile is not profile:
            raise ValueError("program rendering backend returned mismatched identity")
        return rendered


def program_sha256(program: CompiledProgram) -> str:
    if not program.segments:
        raise ValueError("program must contain at least one segment")
    payload = {
        "segments": [
            {
                "duration_seconds": segment.duration_seconds,
                "scene_base": segment.scene_base,
                "source": segment.source,
                "visual_kinds": [kind.value for kind in segment.visual_kinds],
            }
            for segment in program.segments
        ],
        "version": PROGRAM_RENDERER_VERSION,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _idempotency_key(
    *,
    seed: str,
    program_digest: str,
    profile: RenderProfile,
    quality_policy: ProgramQualityPolicy,
) -> str:
    encoded = "\0".join(
        (PROGRAM_RENDERER_VERSION, seed, program_digest, profile.value, quality_policy.value)
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _segment_idempotency_key(program_key: str, segment_index: int) -> str:
    return hashlib.sha256(f"{program_key}:{segment_index}".encode("ascii")).hexdigest()


def _rendered_segment(job: JobResponse, source_sha256: str) -> RenderedSegment:
    if job.status in {RenderJobStatus.FAILED, RenderJobStatus.CANCELLED}:
        return RenderedSegment(
            segment_index=job.segment_index or 0,
            source_sha256=source_sha256,
            status=ProgramRenderStatus.FAILED,
            render_job_id=job.id,
            failure_code=job.failure_code or "render_job_cancelled",
        )
    status = (
        ProgramRenderStatus.QUEUED
        if job.status is RenderJobStatus.QUEUED
        else ProgramRenderStatus.RENDERING
    )
    return RenderedSegment(
        segment_index=job.segment_index or 0,
        source_sha256=source_sha256,
        status=status,
        render_job_id=job.id,
    )
