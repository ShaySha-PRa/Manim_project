from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

import pytest
from manim_workbench_api.database import create_database_engine
from manim_workbench_api.jobs.repository import JobRepository
from manim_workbench_api.jobs.router import complete_render_job
from manim_workbench_api.jobs.service import JobService
from manim_workbench_api.workflows import (
    ProgramRenderSource,
    ProgramRenderStore,
)
from manim_workbench_contracts import (
    RenderArtifactPayload,
    RenderJobCompletion,
    RenderJobHeartbeat,
    RenderJobLeaseRequest,
    RenderJobSubmission,
    RenderProfile,
)
from sqlalchemy import Engine, text

from tests.phase5.api.test_job_lifecycle import _create_schema
from tests.workflows.test_repository import OWNER_A, OWNER_B, PROJECT_A, PROJECT_B
from tests.workflows.test_workflow_artifacts import _scene_run

pytest_plugins = ("tests.workflows.test_repository",)


class _Signals:
    def publish(self, _job_id) -> None:  # type: ignore[no-untyped-def]
        return None


def test_legacy_0008_shape_keeps_teaching_submission_and_claim(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = create_database_engine(f"sqlite:///{tmp_path / 'legacy-jobs.db'}")
    _create_schema(engine)
    repository = JobRepository(engine)
    code_version_id = uuid4()
    source = "from manim import Scene\nclass GeneratedScene(Scene):\n    pass\n"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO code_versions (id,source_code,source_sha256,scene_class) "
                "VALUES (:id,:source,:hash,'GeneratedScene')"
            ),
            {
                "id": str(code_version_id),
                "source": source,
                "hash": sha256(source.encode()).hexdigest(),
            },
        )
    job, created = repository.create_or_get(
        RenderJobSubmission(
            project_id=uuid4(),
            owner_id=uuid4(),
            code_version_id=code_version_id,
            profile=RenderProfile.PREVIEW,
            idempotency_key="legacy-teaching-render-job",
        )
    )

    claim = repository.claim(job.id, "legacy-runner", 30)

    assert created is True
    assert job.program_render_segment_id is None
    assert claim.record is not None
    assert claim.work_item is not None
    assert claim.work_item.content_plan_version_id == code_version_id


def _source() -> ProgramRenderSource:
    source = "from manim import Scene\nclass ScientificScene(Scene):\n    pass\n"
    return ProgramRenderSource(
        source_code=source,
        source_sha256=sha256(source.encode()).hexdigest(),
        scene_class="ScientificScene",
        target_duration_seconds=45,
    )


def _persisted_segment(engine: Engine):  # type: ignore[no-untyped-def]
    scene_run = _scene_run(engine)
    run, segments = ProgramRenderStore(engine).create_or_get(
        scene_block_run_id=scene_run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        profile=RenderProfile.PREVIEW,
        program_sha256="f" * 64,
        quality_policy="scientific",
        segment_sources=(_source(),),
    )
    return run, segments[0]


def test_scientific_job_claims_persisted_source_without_content_plan(engine: Engine) -> None:
    run, segment = _persisted_segment(engine)
    repository = JobRepository(engine)
    job, created = repository.create_or_get(
        RenderJobSubmission(
            project_id=PROJECT_A,
            owner_id=OWNER_A,
            program_render_segment_id=segment.id,
            profile=RenderProfile.PREVIEW,
            idempotency_key="scientific-typed-render-job",
            concat_group_id=uuid4(),
            segment_index=0,
        )
    )
    assert created is True
    ProgramRenderStore(engine).attach_job(run.id, 0, job.id)

    lease = JobService(repository, _Signals()).claim(
        job.id,
        RenderJobLeaseRequest(runner_id="typed-source-runner", lease_seconds=30),
    )

    assert lease.code_version_id is None
    assert lease.program_render_segment_id == segment.id
    assert lease.content_plan_version_id is None
    assert lease.source_code == _source().source_code


def test_typed_segment_completion_uses_program_quality_gate_not_legacy_report(
    engine: Engine,
) -> None:
    run, segment = _persisted_segment(engine)
    repository = JobRepository(engine)
    signals = _Signals()
    jobs = JobService(repository, signals)
    job, _ = repository.create_or_get(
        RenderJobSubmission(
            project_id=PROJECT_A,
            owner_id=OWNER_A,
            program_render_segment_id=segment.id,
            profile=RenderProfile.PREVIEW,
            idempotency_key="typed-segment-quality-completion",
            concat_group_id=uuid4(),
            segment_index=0,
        )
    )
    ProgramRenderStore(engine).attach_job(run.id, 0, job.id)
    lease = jobs.claim(
        job.id,
        RenderJobLeaseRequest(runner_id="typed-quality-runner", lease_seconds=60),
    )
    jobs.start(
        job.id,
        RenderJobHeartbeat(lease_token=lease.lease_token, extend_seconds=60),
    )
    artifacts = tuple(
        RenderArtifactPayload(
            kind=kind,
            relative_path=f"{job.id}/attempt-1/{name}",
            sha256=sha256(kind.encode()).hexdigest(),
            byte_size=1,
        )
        for kind, name in (
            ("video", "video.mp4"),
            ("thumbnail", "thumbnail.jpg"),
            ("render_log", "render.log"),
            ("metadata", "metadata.json"),
        )
    )

    response = complete_render_job(
        job.id,
        RenderJobCompletion(lease_token=lease.lease_token, artifacts=artifacts),
        request_token="internal-test-token",
        expected_token="internal-test-token",
        engine=engine,
        publisher=signals,
    )

    assert response.status.value == "succeeded"  # type: ignore[union-attr]
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM artifacts WHERE render_job_id=:job"),
            {"job": str(job.id)},
        ).scalar_one() == 4
        assert connection.execute(
            text("SELECT COUNT(*) FROM quality_reports WHERE render_job_id=:job"),
            {"job": str(job.id)},
        ).scalar_one() == 0


def test_program_segment_attach_rejects_cross_owner_job(engine: Engine) -> None:
    _run, segment = _persisted_segment(engine)
    with pytest.raises(ValueError, match="identity is invalid"):
        JobRepository(engine).create_or_get(
            RenderJobSubmission(
                project_id=PROJECT_B,
                owner_id=OWNER_B,
                program_render_segment_id=segment.id,
                profile=RenderProfile.PREVIEW,
                idempotency_key="cross-owner-typed-render-job",
                concat_group_id=uuid4(),
                segment_index=0,
            )
        )


def test_program_source_hash_mismatch_is_not_claimable(engine: Engine) -> None:
    run, segment = _persisted_segment(engine)
    repository = JobRepository(engine)
    job, _ = repository.create_or_get(
        RenderJobSubmission(
            project_id=PROJECT_A,
            owner_id=OWNER_A,
            program_render_segment_id=segment.id,
            profile=RenderProfile.PREVIEW,
            idempotency_key="hash-mismatch-typed-render-job",
            concat_group_id=uuid4(),
            segment_index=0,
        )
    )
    ProgramRenderStore(engine).attach_job(run.id, 0, job.id)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE program_render_segments SET source_code='tampered' WHERE id=:id"),
            {"id": str(segment.id)},
        )

    claim = repository.claim(job.id, "typed-source-runner", 30)
    assert claim.record is None
    assert claim.work_item is None
    assert claim.work_item_invalid is True
