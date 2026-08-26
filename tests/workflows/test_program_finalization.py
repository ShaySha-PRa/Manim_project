from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import av
import pytest
from manim_workbench_api.compiler.base import CompiledProgram, CompiledSegment
from manim_workbench_api.program_rendering import (
    ProgramPublicationService,
    ProgramQualityPolicy,
    ProgramRenderRequest,
    ProgramRenderStatus,
    RenderedSegment,
    SegmentRenderEvidence,
    program_sha256,
)
from manim_workbench_contracts import RenderProfile
from manim_workbench_runner.rendering import ClipInput


def _program(count: int) -> CompiledProgram:
    return CompiledProgram(
        segments=tuple(
            CompiledSegment(
                source=f"from manim import Scene\n# segment-{index}",
                scene_base="Scene",
                visual_kinds=(),
                duration_seconds=15,
            )
            for index in range(count)
        )
    )


def _request(program: CompiledProgram) -> ProgramRenderRequest:
    return ProgramRenderRequest(
        owner_id=uuid4(),
        project_id=uuid4(),
        program=program,
        program_sha256=program_sha256(program),
        profile=RenderProfile.PREVIEW,
        idempotency_key="a" * 64,
        deadline_seconds=900,
        quality_policy=ProgramQualityPolicy.TEACHING,
    )


def _write_clip(path: Path, frames: int = 6) -> None:
    output = av.open(str(path), mode="w")
    stream = output.add_stream("h264", rate=15)
    stream.width = 160
    stream.height = 90
    stream.pix_fmt = "yuv420p"
    for _ in range(frames):
        frame = av.VideoFrame(width=160, height=90, format="yuv420p")
        frame.planes[0].update(bytes(160 * 90))
        frame.planes[1].update(bytes(80 * 45))
        frame.planes[2].update(bytes(80 * 45))
        packet = stream.encode(frame)
        if packet:
            output.mux(packet)
    packet = stream.encode(None)
    if packet:
        output.mux(packet)
    output.close()


def _success_evidence(
    request: ProgramRenderRequest,
    root: Path,
) -> tuple[SegmentRenderEvidence, ...]:
    evidence = []
    for index, segment in enumerate(request.program.segments):
        path = root / f"segment-{index}.mp4"
        _write_clip(path)
        video_digest = sha256(path.read_bytes()).hexdigest()
        evidence.append(
            SegmentRenderEvidence(
                rendered=RenderedSegment(
                    segment_index=index,
                    source_sha256=sha256(segment.source.encode("utf-8")).hexdigest(),
                    status=ProgramRenderStatus.SUCCEEDED,
                    render_job_id=uuid4(),
                    artifact_id=uuid4(),
                    artifact_sha256=video_digest,
                ),
                clip=ClipInput(path, request.profile, video_digest),
            )
        )
    return tuple(evidence)


class _QualityGate:
    def __init__(self, findings: tuple[str, ...] = ()) -> None:
        self.findings = findings
        self.policies = []

    def evaluate(self, composition, *, policy):  # type: ignore[no-untyped-def]
        del composition
        self.policies.append(policy)
        return self.findings


class _Publisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = []
        self.artifact_id = uuid4()

    def publish(self, request, composition):  # type: ignore[no-untyped-def]
        self.calls.append((request, composition))
        if self.fail:
            raise OSError("publish failed")
        return self.artifact_id


@pytest.mark.parametrize("failed_index", [0, 1, 2])
def test_any_failed_segment_preserves_evidence_and_blocks_publication(
    tmp_path: Path,
    failed_index: int,
) -> None:
    request = _request(_program(3))
    evidence = list(_success_evidence(request, tmp_path))
    failed = evidence[failed_index].rendered
    evidence[failed_index] = SegmentRenderEvidence(
        rendered=RenderedSegment(
            segment_index=failed_index,
            source_sha256=failed.source_sha256,
            status=ProgramRenderStatus.FAILED,
            render_job_id=failed.render_job_id,
            failure_code="sandbox_timeout",
        ),
        clip=None,
    )
    publisher = _Publisher()

    result = ProgramPublicationService(_QualityGate(), publisher).finalize(
        request,
        tuple(evidence),
        output=tmp_path / "program.mp4",
        staging_root=tmp_path,
    )

    assert result.status is ProgramRenderStatus.FAILED
    assert result.failure_code == "segment_failed"
    assert result.artifact_id is None
    assert result.segments[failed_index].failure_code == "sandbox_timeout"
    assert publisher.calls == []


def test_path_specific_quality_failure_does_not_publish_clip(tmp_path: Path) -> None:
    request = _request(_program(1))
    evidence = _success_evidence(request, tmp_path)
    quality = _QualityGate(("duration_too_short",))
    publisher = _Publisher()

    result = ProgramPublicationService(quality, publisher).finalize(
        request,
        evidence,
        output=tmp_path / "unused.mp4",
        staging_root=tmp_path,
    )

    assert result.status is ProgramRenderStatus.FAILED
    assert result.failure_code == "quality_gate_failed"
    assert quality.policies == [ProgramQualityPolicy.TEACHING]
    assert publisher.calls == []
    assert evidence[0].clip is not None and evidence[0].clip.path.exists()


def test_all_segments_publish_one_complete_program_artifact(tmp_path: Path) -> None:
    request = _request(_program(2))
    evidence = _success_evidence(request, tmp_path)
    publisher = _Publisher()

    result = ProgramPublicationService(_QualityGate(), publisher).finalize(
        request,
        evidence,
        output=tmp_path / "program.mp4",
        staging_root=tmp_path,
    )

    assert result.status is ProgramRenderStatus.SUCCEEDED
    assert result.artifact_id == publisher.artifact_id
    assert len(publisher.calls) == 1
    assert publisher.calls[0][1].media.frame_count >= 10


def test_failed_atomic_publish_discards_only_composed_staging_output(tmp_path: Path) -> None:
    request = _request(_program(2))
    evidence = _success_evidence(request, tmp_path)
    output = tmp_path / "program.mp4"

    result = ProgramPublicationService(_QualityGate(), _Publisher(fail=True)).finalize(
        request,
        evidence,
        output=output,
        staging_root=tmp_path,
    )

    assert result.status is ProgramRenderStatus.FAILED
    assert result.failure_code == "artifact_publish_failed"
    assert not output.exists()
    assert all(item.clip is not None and item.clip.path.exists() for item in evidence)
