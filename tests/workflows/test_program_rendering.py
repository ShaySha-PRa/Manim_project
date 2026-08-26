from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

import pytest
from manim_workbench_api.compiler.base import CompiledProgram, CompiledSegment
from manim_workbench_api.jobs.models import JobResponse
from manim_workbench_api.program_rendering import (
    CodeVersionProgramSegmentStore,
    JobProgramRenderBackend,
    ProgramQualityPolicy,
    ProgramRenderService,
    ProgramRenderStatus,
    RenderedProgram,
    RenderedSegment,
    StagedProgramSegment,
    TypedProgramSegmentStore,
    program_sha256,
)
from manim_workbench_contracts import (
    CodeGenerationCategory,
    CodeGenerationMode,
    CodeGenerationRequest,
    CodeVersion,
    ProgramRenderSegment,
    ProgramRenderSegmentStatus,
    RenderJobStatus,
    RenderProfile,
)
from manim_workbench_contracts.ir import VisualKind


def _program() -> CompiledProgram:
    return CompiledProgram(
        segments=(
            CompiledSegment(
                source="from manim import Scene\n# first",
                scene_base="Scene",
                visual_kinds=(VisualKind.FORMULA,),
                duration_seconds=15,
            ),
            CompiledSegment(
                source="from manim import ThreeDScene\n# second",
                scene_base="ThreeDScene",
                visual_kinds=(VisualKind.THREE_D,),
                duration_seconds=20,
            ),
        )
    )


class _Backend:
    def __init__(self) -> None:
        self.requests = []

    def submit(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return RenderedProgram(
            program_sha256=request.program_sha256,
            profile=request.profile,
            status=ProgramRenderStatus.QUEUED,
            segments=tuple(
                RenderedSegment(
                    segment_index=index,
                    source_sha256="a" * 64,
                    status=ProgramRenderStatus.QUEUED,
                )
                for index, _segment in enumerate(request.program.segments)
            ),
        )


def test_render_program_submits_full_ordered_program_with_bounded_identity() -> None:
    backend = _Backend()
    owner_id = uuid4()
    project_id = uuid4()
    service = ProgramRenderService(
        backend,
        owner_id=owner_id,
        project_id=project_id,
        idempotency_seed="scene-block-version-123",
        deadline_seconds=900,
        quality_policy=ProgramQualityPolicy.TEACHING,
    )

    rendered = service.render_program(_program(), RenderProfile.PREVIEW)

    request = backend.requests[0]
    assert request.owner_id == owner_id
    assert request.project_id == project_id
    assert request.program == _program()
    assert request.program_sha256 == program_sha256(_program())
    assert request.profile is RenderProfile.PREVIEW
    assert request.deadline_seconds == 900
    assert request.quality_policy is ProgramQualityPolicy.TEACHING
    assert len(request.idempotency_key) == 64
    assert rendered.status is ProgramRenderStatus.QUEUED
    assert tuple(item.segment_index for item in rendered.segments) == (0, 1)


def test_program_and_idempotency_hashes_are_deterministic_and_order_sensitive() -> None:
    program = _program()
    reversed_program = CompiledProgram(segments=tuple(reversed(program.segments)))
    changed_source = replace(
        program,
        segments=(replace(program.segments[0], source="# changed"), program.segments[1]),
    )
    assert program_sha256(program) == program_sha256(_program())
    assert program_sha256(program) != program_sha256(reversed_program)
    assert program_sha256(program) != program_sha256(changed_source)

    backend = _Backend()
    service = ProgramRenderService(
        backend,
        owner_id=uuid4(),
        project_id=uuid4(),
        idempotency_seed="scene-block-version-123",
        deadline_seconds=900,
        quality_policy=ProgramQualityPolicy.SCIENTIFIC,
    )
    service.render_program(program, RenderProfile.PREVIEW)
    service.render_program(program, RenderProfile.FINAL)
    assert backend.requests[0].idempotency_key != backend.requests[1].idempotency_key


def test_program_render_contract_rejects_unbounded_or_inconsistent_results() -> None:
    with pytest.raises(ValueError, match="at least one segment"):
        program_sha256(CompiledProgram(segments=()))
    with pytest.raises(ValueError, match="deadline_seconds"):
        ProgramRenderService(
            _Backend(),
            owner_id=uuid4(),
            project_id=uuid4(),
            idempotency_seed="scene-block-version-123",
            deadline_seconds=0,
            quality_policy=ProgramQualityPolicy.TEACHING,
        )
    with pytest.raises(ValueError, match="contiguous and ordered"):
        RenderedProgram(
            program_sha256="a" * 64,
            profile=RenderProfile.PREVIEW,
            status=ProgramRenderStatus.RENDERING,
            segments=(
                RenderedSegment(
                    segment_index=1,
                    source_sha256="b" * 64,
                    status=ProgramRenderStatus.RENDERING,
                ),
            ),
        )


def test_failed_program_has_stable_failure_without_published_artifact() -> None:
    failed_segment = RenderedSegment(
        segment_index=0,
        source_sha256="b" * 64,
        status=ProgramRenderStatus.FAILED,
        render_job_id=uuid4(),
        failure_code="sandbox_timeout",
    )
    rendered = RenderedProgram(
        program_sha256="a" * 64,
        profile=RenderProfile.FINAL,
        status=ProgramRenderStatus.FAILED,
        segments=(failed_segment,),
        failure_code="segment_failed",
    )
    assert rendered.artifact_id is None
    with pytest.raises(ValueError, match="failed program requires only failure_code"):
        replace(rendered, artifact_id=uuid4())


class _SegmentStore:
    def __init__(self) -> None:
        self.staged = []

    def stage(self, request, *, segment_index, concat_group_id):  # type: ignore[no-untyped-def]
        self.staged.append(
            (request.program.segments[segment_index], segment_index, concat_group_id)
        )
        return StagedProgramSegment(
            code_version_id=uuid4(),
            source_sha256=sha256(
                request.program.segments[segment_index].source.encode("utf-8")
            ).hexdigest(),
        )

    def attach_job(self, segment_index, render_job_id):  # type: ignore[no-untyped-def]
        self.staged[segment_index] += (render_job_id,)


class _Jobs:
    def __init__(self) -> None:
        self.submissions = []

    def submit(self, submission):  # type: ignore[no-untyped-def]
        self.submissions.append(submission)
        return (
            JobResponse(
                id=uuid4(),
                project_id=submission.project_id,
                owner_id=submission.owner_id,
                code_version_id=submission.code_version_id,
                program_render_segment_id=submission.program_render_segment_id,
                profile=submission.profile,
                status=RenderJobStatus.QUEUED,
                created_at=datetime.now(timezone.utc),
                attempt_count=0,
                state_version=0,
                concat_group_id=submission.concat_group_id,
                segment_index=submission.segment_index,
            ),
            True,
        )


def test_job_backend_stages_and_submits_every_segment_in_stable_group_order() -> None:
    segment_store = _SegmentStore()
    jobs = _Jobs()
    backend = JobProgramRenderBackend(segment_store, jobs)
    service = ProgramRenderService(
        backend,
        owner_id=uuid4(),
        project_id=uuid4(),
        idempotency_seed="scene-block-version-123",
        deadline_seconds=900,
        quality_policy=ProgramQualityPolicy.TEACHING,
    )

    rendered = service.render_program(_program(), RenderProfile.PREVIEW)

    assert len(segment_store.staged) == len(jobs.submissions) == 2
    assert [item[1] for item in segment_store.staged] == [0, 1]
    group_ids = {item.concat_group_id for item in jobs.submissions}
    assert len(group_ids) == 1
    assert None not in group_ids
    assert [item.segment_index for item in jobs.submissions] == [0, 1]
    assert jobs.submissions[0].idempotency_key != jobs.submissions[1].idempotency_key
    assert tuple(item.render_job_id for item in rendered.segments)
    assert rendered.status is ProgramRenderStatus.QUEUED


def test_typed_segment_store_submits_real_program_segment_sources() -> None:
    program = _program()
    persisted = tuple(
        ProgramRenderSegment(
            id=uuid4(),
            program_render_run_id=uuid4(),
            segment_index=index,
            source_sha256=sha256(segment.source.encode()).hexdigest(),
            scene_class="GeneratedScene",
            target_duration_seconds=30,
            status=ProgramRenderSegmentStatus.PENDING,
        )
        for index, segment in enumerate(program.segments)
    )
    jobs = _Jobs()
    attached = []
    backend = JobProgramRenderBackend(
        TypedProgramSegmentStore(
            persisted,
            lambda index, job_id: attached.append((index, job_id)),
        ),
        jobs,
    )
    ProgramRenderService(
        backend,
        owner_id=uuid4(),
        project_id=uuid4(),
        idempotency_seed="scientific-scene-block-version",
        deadline_seconds=900,
        quality_policy=ProgramQualityPolicy.SCIENTIFIC,
    ).render_program(program, RenderProfile.PREVIEW)

    assert [item.code_version_id for item in jobs.submissions] == [None, None]
    assert [item.program_render_segment_id for item in jobs.submissions] == [
        item.id for item in persisted
    ]
    assert [item[0] for item in attached] == [0, 1]


class _CodeRepository:
    def __init__(self) -> None:
        self.versions = {}
        self.saves = 0
        self.latest_id = None

    def find_compiled_segment(
        self, request, *, source_sha256, prompt_template_version
    ):  # type: ignore[no-untyped-def]
        del request
        return self.versions.get((source_sha256, prompt_template_version))

    def save_success(self, request, **values):  # type: ignore[no-untyped-def]
        self.saves += 1
        response = values["response"]
        template = values["prompt_template_version"]
        digest = sha256(response.code.encode("utf-8")).hexdigest()
        version = CodeVersion(
            id=uuid4(),
            project_id=request.project_id,
            owner_id=request.owner_id,
            version=self.saves,
            parent_version_id=self.latest_id,
            created_at=datetime.now(timezone.utc),
            prompt_version_id=request.prompt_version_id,
            content_plan_version_id=request.content_plan_version_id,
            source_code=response.code,
            source_sha256=digest,
            scene_class=response.scene_class,
            engine="manimce",
            engine_version="0.21.0",
            category=request.category,
            generation_mode=CodeGenerationMode.COMPILED_IR,
            prompt_template_version=template,
        )
        self.latest_id = version.id
        self.versions[(digest, template)] = version
        return version


def test_code_version_segment_store_reuses_exact_immutable_segment() -> None:
    owner_id = uuid4()
    project_id = uuid4()
    code_request = CodeGenerationRequest(
        project_id=project_id,
        owner_id=owner_id,
        prompt_version_id=uuid4(),
        content_plan_version_id=uuid4(),
        category=CodeGenerationCategory.MIXED,
    )
    repository = _CodeRepository()
    store = CodeVersionProgramSegmentStore(repository, code_request)  # type: ignore[arg-type]
    capture = _Backend()
    ProgramRenderService(
        capture,
        owner_id=owner_id,
        project_id=project_id,
        idempotency_seed="scene-block-version-123",
        deadline_seconds=900,
        quality_policy=ProgramQualityPolicy.TEACHING,
    ).render_program(_program(), RenderProfile.PREVIEW)
    request = capture.requests[0]
    group_id = uuid4()

    first = store.stage(request, segment_index=0, concat_group_id=group_id)
    repeated = store.stage(request, segment_index=0, concat_group_id=group_id)
    second = store.stage(request, segment_index=1, concat_group_id=group_id)

    assert first == repeated
    assert first.code_version_id != second.code_version_id
    assert repository.saves == 2
