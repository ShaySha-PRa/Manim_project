from __future__ import annotations

import json
import os
import subprocess
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import av
import pytest
from manim_workbench_api.code_generation.gallery_fixtures import (
    fixed_in_frame_storyboard,
    opening_manim_formula_storyboard,
)
from manim_workbench_api.code_generation.ir_compiler import compile_storyboard
from manim_workbench_api.code_generation.repository import CodeGenerationRepository
from manim_workbench_api.database import create_database_engine
from manim_workbench_api.jobs.repository import JobRepository
from manim_workbench_api.jobs.service import JobService
from manim_workbench_api.program_rendering import (
    CodeVersionProgramSegmentStore,
    JobProgramRenderBackend,
    ProgramPublicationService,
    ProgramQualityPolicy,
    ProgramRenderService,
    ProgramRenderStatus,
    RenderedSegment,
    SegmentRenderEvidence,
)
from manim_workbench_contracts import (
    CodeGenerationCategory,
    CodeGenerationRequest,
    RenderJobHeartbeat,
    RenderJobLeaseRequest,
    RenderProfile,
)
from manim_workbench_contracts.ir import SceneStoryboard
from manim_workbench_runner.phase5_runtime import Phase5SandboxAdapter
from manim_workbench_runner.queue.types import JobControl, SandboxWorkItem
from manim_workbench_runner.rendering import ClipInput
from manim_workbench_runner.rendering.models import MANIM_IMAGE
from sqlalchemy import text

from tests.workflows.migration_support import upgrade_workflow_database

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _docker_ready() -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", MANIM_IMAGE],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode == 0


class _Signals:
    def __init__(self) -> None:
        self.job_ids = []

    def publish(self, job_id):  # type: ignore[no-untyped-def]
        self.job_ids.append(job_id)


class _CaptureBackend:
    def __init__(self, backend) -> None:  # type: ignore[no-untyped-def]
        self.backend = backend
        self.request = None

    def submit(self, request):  # type: ignore[no-untyped-def]
        self.request = request
        return self.backend.submit(request)


class _AllowQuality:
    def evaluate(self, composition, *, policy):  # type: ignore[no-untyped-def]
        assert composition.media.frame_count > 0
        assert policy is ProgramQualityPolicy.TEACHING
        return ()


class _AtomicVideoPublisher:
    def __init__(self, destination: Path) -> None:
        self.destination = destination
        self.artifact_id = uuid4()

    def publish(self, request, composition):  # type: ignore[no-untyped-def]
        del request
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(composition.path, self.destination)
        return self.artifact_id


@pytest.mark.skipif(not _docker_ready(), reason="Docker Manim image is not present")
def test_real_docker_renders_and_composes_ordered_2d_3d_2d_program(tmp_path: Path) -> None:
    database_path = tmp_path / "program-rendering.db"
    upgrade_workflow_database(database_path)
    engine = create_database_engine(f"sqlite:///{database_path}")
    owner_id = uuid4()
    project_id = uuid4()
    prompt_id = uuid4()
    plan_id = uuid4()
    _seed_versions(engine, owner_id, project_id, prompt_id, plan_id)
    formula = opening_manim_formula_storyboard().steps[0]
    surface = fixed_in_frame_storyboard().steps[0]
    summary = formula.model_copy(update={"goal": "Summarize the result"})
    program = compile_storyboard(
        SceneStoryboard(
            target_duration_seconds=48,
            steps=(formula, surface, summary),
        )
    )
    assert [segment.scene_base for segment in program.segments] == [
        "Scene",
        "ThreeDScene",
        "Scene",
    ]
    code_request = CodeGenerationRequest(
        project_id=project_id,
        owner_id=owner_id,
        prompt_version_id=prompt_id,
        content_plan_version_id=plan_id,
        category=CodeGenerationCategory.MIXED,
    )
    signals = _Signals()
    jobs = JobService(JobRepository(engine), signals)
    backend = _CaptureBackend(
        JobProgramRenderBackend(
            CodeVersionProgramSegmentStore(CodeGenerationRepository(engine), code_request),
            jobs,
        )
    )
    submitted = ProgramRenderService(
        backend,
        owner_id=owner_id,
        project_id=project_id,
        idempotency_seed="docker-2d-3d-2d-program",
        deadline_seconds=900,
        quality_policy=ProgramQualityPolicy.TEACHING,
    ).render_program(program, RenderProfile.PREVIEW)
    assert submitted.status is ProgramRenderStatus.QUEUED
    assert len(signals.job_ids) == 3

    runtime_root = tmp_path / "runner"
    sandbox = Phase5SandboxAdapter(runtime_root=runtime_root)
    for job_id in signals.job_ids:
        lease = jobs.claim(
            job_id,
            RenderJobLeaseRequest(runner_id="workflow-docker-test", lease_seconds=300),
        )
        jobs.start(
            job_id,
            RenderJobHeartbeat(lease_token=lease.lease_token, extend_seconds=300),
        )
        execution = sandbox.execute(
            SandboxWorkItem(lease=lease),
            control_probe=lambda: JobControl(active=True, cancellation_requested=False),
        )
        jobs.complete(
            job_id,
            completion=_completion(lease.lease_token, execution.artifacts),
        )

    evidence = _load_evidence(engine, runtime_root, submitted.segments)
    assert backend.request is not None
    staging = tmp_path / "composition-staging"
    staging.mkdir()
    final_video = tmp_path / "published" / "scene-block.mp4"
    publisher = _AtomicVideoPublisher(final_video)
    finalized = ProgramPublicationService(_AllowQuality(), publisher).finalize(
        backend.request,
        evidence,
        output=staging / "scene-block.mp4",
        staging_root=staging,
    )

    assert finalized.status is ProgramRenderStatus.SUCCEEDED
    assert finalized.artifact_id == publisher.artifact_id
    assert final_video.is_file()
    with av.open(str(final_video)) as container:
        frames = sum(1 for _ in container.decode(video=0))
    assert frames > 0
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT concat_group_id, segment_index, status FROM render_jobs "
                "ORDER BY segment_index"
            )
        ).all()
        artifact_counts = connection.execute(
            text(
                "SELECT render_job_id, COUNT(*) FROM artifacts "
                "GROUP BY render_job_id ORDER BY render_job_id"
            )
        ).all()
    assert len({row[0] for row in rows}) == 1
    assert [row[1] for row in rows] == [0, 1, 2]
    assert {row[2] for row in rows} == {"succeeded"}
    assert [count for _job_id, count in artifact_counts] == [4, 4, 4]
    containers = subprocess.run(
        ["docker", "ps", "-a", "--filter", "name=manim-wb-", "--format", "{{.Names}}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert not containers.stdout.strip()


def _completion(lease_token, artifacts):  # type: ignore[no-untyped-def]
    from manim_workbench_contracts import RenderJobCompletion

    return RenderJobCompletion(lease_token=lease_token, artifacts=artifacts)


def _seed_versions(engine, owner_id, project_id, prompt_id, plan_id) -> None:  # type: ignore[no-untyped-def]
    now = "2026-08-23T00:00:00+00:00"
    content = json.dumps({"target_duration_seconds": 16})
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id, email, created_at) VALUES (:id, :email, :now)"),
            {"id": str(owner_id), "email": "workflow-docker@example.com", "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO projects (id, owner_id, title, created_at) "
                "VALUES (:id, :owner_id, :title, :now)"
            ),
            {
                "id": str(project_id),
                "owner_id": str(owner_id),
                "title": "2D 3D 2D Docker",
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO prompt_versions "
                "(id, project_id, owner_id, version, parent_version_id, created_at, prompt) "
                "VALUES (:id, :project_id, :owner_id, 1, NULL, :now, :prompt)"
            ),
            {
                "id": str(prompt_id),
                "project_id": str(project_id),
                "owner_id": str(owner_id),
                "now": now,
                "prompt": "2D formula, 3D surface, 2D summary",
            },
        )
        connection.execute(
            text(
                "INSERT INTO content_plan_versions "
                "(id, project_id, owner_id, version, parent_version_id, created_at, "
                "schema_version, content_json) "
                "VALUES (:id, :project_id, :owner_id, 1, NULL, :now, '1.1', :content)"
            ),
            {
                "id": str(plan_id),
                "project_id": str(project_id),
                "owner_id": str(owner_id),
                "now": now,
                "content": content,
            },
        )


def _load_evidence(engine, runtime_root, submitted_segments):  # type: ignore[no-untyped-def]
    evidence = []
    with engine.connect() as connection:
        for segment in submitted_segments:
            row = connection.execute(
                text(
                    "SELECT id, relative_path, sha256 FROM artifacts "
                    "WHERE render_job_id = :job_id AND kind = 'video'"
                ),
                {"job_id": str(segment.render_job_id)},
            ).mappings().one()
            path = runtime_root / "artifacts" / str(row["relative_path"])
            assert sha256(path.read_bytes()).hexdigest() == row["sha256"]
            evidence.append(
                SegmentRenderEvidence(
                    rendered=RenderedSegment(
                        segment_index=segment.segment_index,
                        source_sha256=segment.source_sha256,
                        status=ProgramRenderStatus.SUCCEEDED,
                        render_job_id=segment.render_job_id,
                        artifact_id=UUID(str(row["id"])),
                        artifact_sha256=str(row["sha256"]),
                    ),
                    clip=ClipInput(
                        path=path,
                        profile=RenderProfile.PREVIEW,
                        sha256=str(row["sha256"]),
                    ),
                )
            )
    return tuple(evidence)
