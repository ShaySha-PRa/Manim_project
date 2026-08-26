"""Finalize a program only after every segment and applicable quality gate succeeds."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from manim_workbench_runner.rendering.concat import (
    ClipInput,
    CompositionResult,
    ConcatError,
    compose_mp4s,
)

from .models import (
    ProgramQualityPolicy,
    ProgramRenderRequest,
    ProgramRenderStatus,
    RenderedProgram,
    RenderedSegment,
)


@dataclass(frozen=True, slots=True)
class SegmentRenderEvidence:
    rendered: RenderedSegment
    clip: ClipInput | None


class ProgramQualityGate(Protocol):
    def evaluate(
        self,
        composition: CompositionResult,
        *,
        policy: ProgramQualityPolicy,
    ) -> tuple[str, ...]: ...


class ProgramArtifactPublisher(Protocol):
    def publish(
        self,
        request: ProgramRenderRequest,
        composition: CompositionResult,
    ) -> UUID: ...


class ProgramPublicationService:
    def __init__(
        self,
        quality_gate: ProgramQualityGate,
        publisher: ProgramArtifactPublisher,
    ) -> None:
        self._quality_gate = quality_gate
        self._publisher = publisher

    def finalize(
        self,
        request: ProgramRenderRequest,
        evidence: tuple[SegmentRenderEvidence, ...],
        *,
        output: Path,
        staging_root: Path,
    ) -> RenderedProgram:
        rendered_segments = tuple(item.rendered for item in evidence)
        if tuple(item.segment_index for item in rendered_segments) != tuple(
            range(len(request.program.segments))
        ):
            return self._failed(request, rendered_segments, "segment_evidence_incomplete")
        failed = next(
            (
                item
                for item in evidence
                if item.rendered.status is ProgramRenderStatus.FAILED
            ),
            None,
        )
        if failed is not None:
            return self._failed(request, rendered_segments, "segment_failed")
        if any(
            item.rendered.status is not ProgramRenderStatus.SUCCEEDED or item.clip is None
            for item in evidence
        ):
            return self._failed(request, rendered_segments, "segment_evidence_incomplete")
        clips = tuple(item.clip for item in evidence if item.clip is not None)
        if any(
            item.rendered.artifact_sha256 != clip.sha256
            or clip.profile is not request.profile
            for item, clip in zip(evidence, clips, strict=True)
        ):
            return self._failed(request, rendered_segments, "segment_artifact_mismatch")
        composition: CompositionResult | None = None
        try:
            composition = compose_mp4s(clips, output, staging_root=staging_root)
            findings = self._quality_gate.evaluate(
                composition,
                policy=request.quality_policy,
            )
            if findings:
                self._discard_composition(composition)
                return self._failed(request, rendered_segments, "quality_gate_failed")
            artifact_id = self._publisher.publish(request, composition)
        except ConcatError:
            return self._failed(request, rendered_segments, "media_validation_failed")
        except (OSError, ValueError):
            if composition is not None:
                self._discard_composition(composition)
            return self._failed(request, rendered_segments, "artifact_publish_failed")
        return RenderedProgram(
            program_sha256=request.program_sha256,
            profile=request.profile,
            status=ProgramRenderStatus.SUCCEEDED,
            segments=rendered_segments,
            artifact_id=artifact_id,
        )

    @staticmethod
    def _failed(
        request: ProgramRenderRequest,
        segments: tuple[RenderedSegment, ...],
        failure_code: str,
    ) -> RenderedProgram:
        return RenderedProgram(
            program_sha256=request.program_sha256,
            profile=request.profile,
            status=ProgramRenderStatus.FAILED,
            segments=segments,
            failure_code=failure_code,
        )

    @staticmethod
    def _discard_composition(composition: CompositionResult) -> None:
        if not composition.reused_single_clip:
            composition.path.unlink(missing_ok=True)
