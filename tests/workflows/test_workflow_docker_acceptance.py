from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import av
import pytest
from manim_workbench_api.code_generation.models import CandidateRenderResult
from manim_workbench_api.code_generation.repository import CodeGenerationRepository
from manim_workbench_api.code_generation.service import CodeGenerationService
from manim_workbench_api.content_plans.models import ProviderResult
from manim_workbench_api.content_plans.repository import ContentPlanRepository
from manim_workbench_api.content_plans.service import ContentPlanService
from manim_workbench_api.database import create_database_engine
from manim_workbench_api.projects.repository import ProjectRepository
from manim_workbench_api.workflows import (
    ScientificSceneAdapter,
    TeachingSceneAdapter,
    WorkflowClipEvidence,
    WorkflowComposer,
)
from manim_workbench_contracts import (
    GlobalBrief,
    Language,
    RenderJobLease,
    RenderProfile,
    SceneBlockVersion,
    ScenePipelineMode,
    VideoWorkflowVersion,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowStylePreset,
)
from manim_workbench_runner.phase5_runtime import Phase5SandboxAdapter
from manim_workbench_runner.queue.types import JobControl, SandboxWorkItem
from manim_workbench_runner.rendering import (
    ClipInput,
    compose_mp4s,
    inspect_clip,
)
from manim_workbench_runner.rendering.models import MANIM_IMAGE
from sqlalchemy import text

from tests.workflows.migration_support import upgrade_workflow_database


def _docker_ready() -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", MANIM_IMAGE],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode == 0


class _TeachingPlanProvider:
    def generate(self, _messages):  # type: ignore[no-untyped-def]
        return ProviderResult(
            model="workflow-docker-teaching-plan",
            content=json.dumps(
                {
                    "outcome": "ready",
                    "plan": {
                        "schema_version": "1.1",
                        "title": "Lorenz equations",
                        "audience": "undergraduate",
                        "language": "zh-CN",
                        "target_duration_seconds": 15,
                        "derivation_style": "conceptual",
                        "explicit_assumptions": [
                            "Use the shared dark_scientific workflow style.",
                            "Use background #101018.",
                            "Use palette #4488ff, #ffcc22, #ff4444.",
                            "Use language zh-CN.",
                            "Notation: x=state",
                            "Scientific parameters: sigma=10, rho=28, beta=2.66667",
                        ],
                        "ambiguities": [],
                        "scenes": [
                            {
                                "scene_number": 1,
                                "teaching_goal": "Introduce the Lorenz equations.",
                                "formula_steps": [
                                    {
                                        "expression": "dx/dt=sigma*(y-x)",
                                        "explanation": "Explain the first state equation.",
                                    }
                                ],
                                "visual_intent": "Show the equation and parameter meaning.",
                                "narration_placeholder": "Introduce the model.",
                            }
                        ],
                    },
                    "clarifications": [],
                    "limitations": [],
                }
            ),
        )


class _UnusedCodeProvider:
    def generate(self, _messages):  # type: ignore[no-untyped-def]
        raise AssertionError("the deterministic teaching compiler must be used")


class _UnusedRenderer:
    def render(self, _source: str, _scene_class: str) -> CandidateRenderResult:
        raise AssertionError("the adapter must not bypass the Docker acceptance renderer")


class _Publisher:
    def __init__(self) -> None:
        self.artifact_id = uuid4()
        self.calls = []

    def publish(self, workflow, manifest, composition):  # type: ignore[no-untyped-def]
        self.calls.append((workflow, manifest, composition))
        return self.artifact_id


def _block(
    *,
    workflow_id: UUID,
    project_id: UUID,
    owner_id: UUID,
    title: str,
    prompt: str,
    mode: ScenePipelineMode,
) -> SceneBlockVersion:
    return SceneBlockVersion(
        id=uuid4(),
        workflow_id=workflow_id,
        project_id=project_id,
        owner_id=owner_id,
        version=1,
        parent_version_id=None,
        title=title,
        prompt=prompt,
        pipeline_mode=mode,
        target_duration_seconds=15,
        created_at=datetime.now(timezone.utc),
    )


def _workflow(
    *,
    workflow_id: UUID,
    project_id: UUID,
    owner_id: UUID,
    brief: GlobalBrief,
    scene_ids: tuple[UUID, ...],
) -> VideoWorkflowVersion:
    nodes = tuple(
        WorkflowNode(id=uuid4(), kind=WorkflowNodeKind.SCENE, scene_block_version_id=scene_id)
        for scene_id in scene_ids
    ) + (
        WorkflowNode(id=uuid4(), kind=WorkflowNodeKind.COMPOSE),
        WorkflowNode(id=uuid4(), kind=WorkflowNodeKind.EXPORT),
    )
    return VideoWorkflowVersion(
        id=uuid4(),
        workflow_id=workflow_id,
        project_id=project_id,
        owner_id=owner_id,
        version=1,
        parent_version_id=None,
        global_brief=brief,
        nodes=nodes,
        edges=tuple(
            WorkflowEdge(source_node_id=nodes[index].id, target_node_id=nodes[index + 1].id)
            for index in range(len(nodes) - 1)
        ),
        created_at=datetime.now(timezone.utc),
    )


def _render_program(
    root: Path,
    *,
    name: str,
    program,  # type: ignore[no-untyped-def]
) -> tuple[Path, int]:
    clips = []
    runtime_root = root / "runner"
    sandbox = Phase5SandboxAdapter(runtime_root=runtime_root)
    for segment in program.segments:
        job_id = uuid4()
        execution = sandbox.execute(
            SandboxWorkItem(
                lease=RenderJobLease(
                    job_id=job_id,
                    program_render_segment_id=uuid4(),
                    target_duration_seconds=segment.duration_seconds,
                    profile=RenderProfile.PREVIEW,
                    scene_class="GeneratedScene",
                    source_code=segment.source,
                    source_sha256=sha256(segment.source.encode("utf-8")).hexdigest(),
                    lease_token="a" * 64,
                    lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                    attempt_number=1,
                )
            ),
            control_probe=lambda: JobControl(
                active=True, cancellation_requested=False
            ),
        )
        video = next(item for item in execution.artifacts if item.kind.value == "video")
        path = runtime_root / "artifacts" / video.relative_path
        clips.append(ClipInput(path, RenderProfile.PREVIEW, video.sha256))
    if len(clips) == 1:
        return clips[0].path, len(clips)
    staging = root / "scene-composition"
    staging.mkdir(exist_ok=True)
    composed = compose_mp4s(
        tuple(clips),
        staging / f"{name}.mp4",
        staging_root=staging,
    )
    return composed.path, len(clips)


@pytest.mark.skipif(not _docker_ready(), reason="Docker Manim image is not present")
def test_real_teaching_lorenz_and_csv_scenes_compose_into_one_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "workflow-docker.db"
    upgrade_workflow_database(database_path)
    database = create_database_engine(f"sqlite:///{database_path}")
    owner_id, project_id, workflow_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(timezone.utc).isoformat()
    with database.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id,email,created_at) VALUES (:id,:email,:now)"),
            {"id": str(owner_id), "email": "docker-acceptance@test.invalid", "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO projects (id,owner_id,title,created_at) "
                "VALUES (:id,:owner_id,:title,:now)"
            ),
            {
                "id": str(project_id),
                "owner_id": str(owner_id),
                "title": "Workflow Docker acceptance",
                "now": now,
            },
        )
    brief = GlobalBrief(
        title="Lorenz system demonstration",
        language=Language.ZH_CN,
        target_duration_seconds=45,
        style_preset=WorkflowStylePreset.DARK_SCIENTIFIC,
        background="#101018",
        palette=("#4488ff", "#ffcc22", "#ff4444"),
        notation={"x": "state"},
        scientific_parameters={"sigma": 10.0, "rho": 28.0, "beta": 8 / 3},
    )
    teaching = _block(
        workflow_id=workflow_id,
        project_id=project_id,
        owner_id=owner_id,
        title="Equations",
        prompt="介绍 Lorenz 方程和三个参数的意义。",
        mode=ScenePipelineMode.TEACHING,
    )
    lorenz = _block(
        workflow_id=workflow_id,
        project_id=project_id,
        owner_id=owner_id,
        title="Lorenz trajectories",
        prompt="展示三个初值只差 1e-5 的 Lorenz 系统轨迹逐渐分离。",
        mode=ScenePipelineMode.SCIENTIFIC,
    )
    csv_scene = _block(
        workflow_id=workflow_id,
        project_id=project_id,
        owner_id=owner_id,
        title="CSV anomaly",
        prompt="从 CSV 展示 temperature/pressure 并突出 2 秒附近异常。",
        mode=ScenePipelineMode.SCIENTIFIC,
    )
    projects = ProjectRepository(database)
    teaching_adapter = TeachingSceneAdapter(
        projects,
        ContentPlanService(ContentPlanRepository(database), _TeachingPlanProvider()),
        CodeGenerationService(
            CodeGenerationRepository(database), _UnusedCodeProvider(), _UnusedRenderer()
        ),
    )
    scientific_adapter = ScientificSceneAdapter(
        projects,
        compute_root=tmp_path / "scientific-compute",
    )
    monkeypatch.setenv(
        "MANIM_WORKBENCH_COMPUTE_ROOT", str(tmp_path / "scientific-compute")
    )
    compiled = (
        teaching_adapter.compile(teaching, brief),
        scientific_adapter.compile(lorenz, brief, previous_scene_summary="Lorenz equations"),
        scientific_adapter.compile(
            csv_scene,
            brief,
            csv_text=(
                "timestamp,temperature,pressure\n"
                "0,21.0,101.2\n1,21.1,101.1\n2,28.9,98.4\n3,21.2,101.0\n"
            ),
            previous_scene_summary="Sensitive trajectories",
        ),
    )
    assert compiled[1].program.segments[0].scene_base == "ThreeDScene"
    assert compiled[1].tool_runs[0].op.value == "lorenz_ensemble"
    assert compiled[2].tool_runs[0].op.value == "csv_anomaly"
    assert compiled[2].tool_runs[0].input_asset_version is not None
    assert compiled[2].tool_runs[0].input_asset_version.columns == (
        "timestamp",
        "temperature",
        "pressure",
    )
    brief_hashes = {dict(item.provenance)["global_brief_sha256"] for item in compiled}
    assert len(brief_hashes) == 1

    evidence = []
    rendered_segment_count = 0
    for index, (block, result) in enumerate(
        zip((teaching, lorenz, csv_scene), compiled, strict=True)
    ):
        clip_path, segment_count = _render_program(
            tmp_path,
            name=f"workflow_scene_{index}",
            program=result.program,
        )
        rendered_segment_count += segment_count
        payload = clip_path.read_bytes()
        descriptor = inspect_clip(
            ClipInput(clip_path, RenderProfile.PREVIEW, sha256(payload).hexdigest())
        )
        evidence.append(
            WorkflowClipEvidence(
                scene_block_version_id=block.id,
                artifact_id=uuid4(),
                owner_id=owner_id,
                project_id=project_id,
                profile=RenderProfile.PREVIEW,
                path=clip_path,
                artifact_sha256=descriptor.sha256,
                byte_size=descriptor.byte_size,
            )
        )
    assert rendered_segment_count == sum(len(item.program.segments) for item in compiled)

    workflow = _workflow(
        workflow_id=workflow_id,
        project_id=project_id,
        owner_id=owner_id,
        brief=brief,
        scene_ids=(teaching.id, lorenz.id, csv_scene.id),
    )
    publisher = _Publisher()
    staging = tmp_path / "workflow-composition"
    staging.mkdir()
    output = staging / "complete-workflow.mp4"
    result = WorkflowComposer(publisher, composer_version="workflow-mvp-v1").compose(
        workflow,
        profile=RenderProfile.PREVIEW,
        clips=tuple(evidence),
        output=output,
        staging_root=staging,
    )
    assert result.succeeded
    assert result.artifact_id == publisher.artifact_id
    assert result.manifest is not None
    assert tuple(item.scene_block_version_id for item in result.manifest.clips) == (
        teaching.id,
        lorenz.id,
        csv_scene.id,
    )
    expected_frames = sum(
        inspect_clip(
            ClipInput(item.path, item.profile, item.artifact_sha256)
        ).frame_count
        for item in evidence
    )
    final_clip = inspect_clip(
        ClipInput(output, RenderProfile.PREVIEW, result.media_sha256 or "")
    )
    assert abs(final_clip.frame_count - expected_frames) <= len(evidence)
    assert result.manifest.total_duration_seconds == pytest.approx(
        sum(item.duration_seconds for item in result.manifest.clips), abs=1 / final_clip.fps
    )
    with av.open(str(output)) as container:
        assert sum(1 for _ in container.decode(video=0)) > 0
    assert len(publisher.calls) == 1
    containers = subprocess.run(
        ["docker", "ps", "-a", "--filter", "name=manim-wb-", "--format", "{{.Names}}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert not containers.stdout.strip()
