from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import av
from manim_workbench_api.compiler.base import CompiledProgram, CompiledSegment
from manim_workbench_api.jobs.dependencies import NullJobSignalPublisher
from manim_workbench_api.jobs.repository import JobRepository
from manim_workbench_api.jobs.service import JobService
from manim_workbench_api.workflows import (
    SceneBlockExecutor,
    SceneCompilation,
    WorkflowArtifactStore,
    WorkflowRepository,
)
from manim_workbench_contracts import (
    CompositionRunStatus,
    RenderProfile,
    SceneBlockRunStatus,
    ScenePipeline,
)
from manim_workbench_contracts.ir import VisualKind
from manim_workbench_runner.queue import (
    PersistentWorkflowTaskExecutor,
    WorkflowTaskLease,
)
from manim_workbench_runner.rendering import ClipInput, compose_mp4s, inspect_clip
from sqlalchemy import Engine, text

from tests.workflows.test_repository import (
    OWNER_A,
    PROJECT_A,
    _workflow_fixture,
)

pytest_plugins = ("tests.workflows.test_repository",)


def _write_clip(path: Path, *, frames: int = 6) -> None:
    output = av.open(str(path), mode="w")
    stream = output.add_stream("h264", rate=15)
    stream.width = 160
    stream.height = 90
    stream.pix_fmt = "yuv420p"
    for _ in range(frames):
        frame = av.VideoFrame(width=160, height=90, format="yuv420p")
        for plane in frame.planes:
            plane.update(bytes(plane.buffer_size))
        packet = stream.encode(frame)
        if packet:
            output.mux(packet)
    packet = stream.encode(None)
    if packet:
        output.mux(packet)
    output.close()


def _program() -> CompiledProgram:
    return CompiledProgram(
        segments=tuple(
            CompiledSegment(
                source=(
                    "from manim import Scene\n"
                    f"class Segment{index}(Scene):\n"
                    "    def construct(self):\n"
                    "        self.wait(1)\n"
                ),
                scene_base="Scene",
                visual_kinds=(VisualKind.FORMULA,),
                duration_seconds=15,
            )
            for index in range(2)
        )
    )


class _TeachingAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def compile(self, block, global_brief, **_kwargs):  # type: ignore[no-untyped-def]
        del global_brief
        self.calls += 1
        return SceneCompilation(
            pipeline=ScenePipeline.TEACHING,
            program=_program(),
            prompt_version_id=uuid4(),
            content_plan_version_id=uuid4(),
            provenance=(("prompt", block.prompt),),
        )


class _ScientificAdapter:
    def compile(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("teaching fixture must not call the scientific adapter")


class _AllowQuality:
    def evaluate(self, composition, *, policy):  # type: ignore[no-untyped-def]
        del policy
        assert composition.media.frame_count > 0
        return ()


def _executor(
    engine: Engine,
    teaching: _TeachingAdapter,
    store: WorkflowArtifactStore,
    artifact_root: Path,
    staging_root: Path,
    *,
    clock=None,  # type: ignore[no-untyped-def]
) -> PersistentWorkflowTaskExecutor:
    return PersistentWorkflowTaskExecutor(
        engine,
        SceneBlockExecutor(teaching, _ScientificAdapter()),
        JobService(JobRepository(engine), NullJobSignalPublisher()),
        _AllowQuality(),
        store,
        render_artifact_root=artifact_root,
        workflow_staging_root=staging_root,
        composer_version="workflow-mvp-v1",
        retry_seconds=5,
        clock=clock,
    )


def _scene_lease(run_id: UUID, block_id: UUID, workflow_id: UUID) -> WorkflowTaskLease:
    return WorkflowTaskLease(
        task_id=uuid4(),
        run_id=run_id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        kind="scene_program",
        lease_token="a" * 64,
        attempt_count=1,
        payload={
            "scene_block_version_id": str(block_id),
            "workflow_version_id": str(workflow_id),
            "profile": "preview",
        },
    )


def _complete_segment(
    engine: Engine,
    artifact_root: Path,
    *,
    program_run_id: UUID,
    segment_index: int,
) -> UUID:
    with engine.connect() as connection:
        job_id = UUID(
            str(
                connection.execute(
                    text(
                        "SELECT render_job_id FROM program_render_segments "
                        "WHERE program_render_run_id=:run AND segment_index=:index"
                    ),
                    {"run": str(program_run_id), "index": segment_index},
                ).scalar_one()
            )
        )
    relative = Path("render-jobs") / f"{job_id}.mp4"
    path = artifact_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_clip(path, frames=6 + segment_index)
    artifact_id = uuid4()
    now = datetime.now(timezone.utc).isoformat()
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE render_jobs SET status='succeeded',finished_at=:now "
                "WHERE id=:job"
            ),
            {"now": now, "job": str(job_id)},
        )
        connection.execute(
            text(
                "INSERT INTO artifacts "
                "(id,project_id,owner_id,render_job_id,kind,relative_path,sha256,byte_size,"
                "created_at) VALUES (:id,:project,:owner,:job,'video',:path,:sha,:size,:now)"
            ),
            {
                "id": str(artifact_id),
                "project": str(PROJECT_A),
                "owner": str(OWNER_A),
                "job": str(job_id),
                "path": relative.as_posix(),
                "sha": sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
                "now": now,
            },
        )
    return artifact_id


def test_scene_executor_recovers_mid_render_without_duplicate_jobs_or_terminal_artifacts(
    engine: Engine, tmp_path: Path
) -> None:
    repository = WorkflowRepository(engine)
    _, first, _, workflow = _workflow_fixture(repository)
    run = repository.create_scene_block_run(
        scene_block_version_id=first.id,
        workflow_version_id=workflow.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        cache_key="a" * 64,
        idempotency_key="real-scene-recovery",
    )
    artifact_root = tmp_path / "artifacts"
    staging_root = tmp_path / "staging"
    store = WorkflowArtifactStore(engine, artifact_root, staging_root)
    teaching = _TeachingAdapter()
    lease = _scene_lease(run.id, first.id, workflow.id)

    first_attempt = _executor(
        engine, teaching, store, artifact_root, staging_root
    ).execute(lease)
    assert first_attempt is not None and first_attempt.retry_at is not None
    with engine.connect() as connection:
        program_run_id = UUID(
            str(
                connection.execute(
                    text(
                        "SELECT id FROM program_render_runs WHERE scene_block_run_id=:run"
                    ),
                    {"run": str(run.id)},
                ).scalar_one()
            )
        )
        assert connection.execute(text("SELECT COUNT(*) FROM render_jobs")).scalar_one() == 2

    _complete_segment(
        engine,
        artifact_root,
        program_run_id=program_run_id,
        segment_index=0,
    )
    restarted = _executor(engine, teaching, store, artifact_root, staging_root)
    second_attempt = restarted.execute(lease)
    assert second_attempt is not None and second_attempt.retry_at is not None
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM render_jobs")).scalar_one() == 2
    assert teaching.calls == 1

    _complete_segment(
        engine,
        artifact_root,
        program_run_id=program_run_id,
        segment_index=1,
    )
    assert _executor(engine, teaching, store, artifact_root, staging_root).execute(lease) is None
    projected = repository.get_scene_block_run(run.id, PROJECT_A, OWNER_A)
    assert projected.status is SceneBlockRunStatus.SUCCEEDED
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM workflow_artifacts WHERE scene_block_run_id=:run"
            ),
            {"run": str(run.id)},
        ).scalar_one() == 1
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM scene_block_run_events WHERE run_id=:run "
                "AND status IN ('succeeded','failed','asset_required','needs_confirmation')"
            ),
            {"run": str(run.id)},
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT status FROM program_render_runs WHERE id=:run"),
            {"run": str(program_run_id)},
        ).scalar_one() == "succeeded"
    assert teaching.calls == 1


def _publish_scene_fixture(
    repository: WorkflowRepository,
    store: WorkflowArtifactStore,
    staging_root: Path,
    *,
    block_id: UUID,
    workflow_id: UUID,
    name: str,
) -> tuple[UUID, Path]:
    run = repository.create_scene_block_run(
        scene_block_version_id=block_id,
        workflow_version_id=workflow_id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        cache_key=sha256(name.encode()).hexdigest(),
        idempotency_key=f"composition-scene-{name}",
    )
    source = staging_root / f"{name}.mp4"
    _write_clip(source)
    descriptor = inspect_clip(
        ClipInput(
            source,
            RenderProfile.FINAL,
            sha256(source.read_bytes()).hexdigest(),
        )
    )
    artifact = store.publish(
        source,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        profile=RenderProfile.FINAL,
        duration_seconds=descriptor.duration_seconds,
        scene_block_run_id=run.id,
    )
    repository.append_scene_block_run_event(
        run_id=run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        expected_state_version=0,
        status=SceneBlockRunStatus.SUCCEEDED,
        pipeline_used=ScenePipeline.TEACHING,
        final_artifact_id=artifact.id,
    )
    return artifact.id, store.verified_path(artifact)


def test_composition_executor_recovers_after_atomic_publish_before_terminal_commit(
    engine: Engine, tmp_path: Path
) -> None:
    repository = WorkflowRepository(engine)
    _, first, second, workflow = _workflow_fixture(repository)
    artifact_root = tmp_path / "artifacts"
    staging_root = tmp_path / "staging"
    store = WorkflowArtifactStore(engine, artifact_root, staging_root)
    first_artifact, first_path = _publish_scene_fixture(
        repository,
        store,
        staging_root,
        block_id=first.id,
        workflow_id=workflow.id,
        name="first",
    )
    second_artifact, second_path = _publish_scene_fixture(
        repository,
        store,
        staging_root,
        block_id=second.id,
        workflow_id=workflow.id,
        name="second",
    )
    run = repository.create_composition_run(
        workflow_version_id=workflow.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        profile=RenderProfile.FINAL,
        cache_key="f" * 64,
        idempotency_key="composition-publish-recovery",
    )
    repository.append_composition_run_event(
        run_id=run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        expected_state_version=0,
        status=CompositionRunStatus.COMPOSING,
    )
    clips = []
    for path in (first_path, second_path):
        clips.append(
            ClipInput(
                path,
                RenderProfile.FINAL,
                sha256(path.read_bytes()).hexdigest(),
            )
        )
    composition = compose_mp4s(
        tuple(clips), staging_root / "published-before-terminal.mp4", staging_root=staging_root
    )
    published = store.publish(
        composition.path,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        profile=RenderProfile.FINAL,
        duration_seconds=composition.media.duration_seconds,
        composition_run_id=run.id,
    )

    lease = WorkflowTaskLease(
        task_id=uuid4(),
        run_id=run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        kind="composition",
        lease_token="b" * 64,
        attempt_count=2,
        payload={
            "workflow_version_id": str(workflow.id),
            "profile": "final",
            "artifact_ids": [str(first_artifact), str(second_artifact)],
        },
    )
    teaching = _TeachingAdapter()
    assert _executor(engine, teaching, store, artifact_root, staging_root).execute(lease) is None
    projected = repository.get_composition_run(run.id, PROJECT_A, OWNER_A)
    assert projected.status is CompositionRunStatus.SUCCEEDED
    assert projected.artifact_id == published.id
    assert projected.manifest is not None
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM workflow_artifacts WHERE composition_run_id=:run"
            ),
            {"run": str(run.id)},
        ).scalar_one() == 1
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM workflow_composition_run_events WHERE run_id=:run "
                "AND status IN ('succeeded','failed','not_ready_to_compose')"
            ),
            {"run": str(run.id)},
        ).scalar_one() == 1
    assert teaching.calls == 0
