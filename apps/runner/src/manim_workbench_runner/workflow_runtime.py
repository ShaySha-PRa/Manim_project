"""Production construction for the persistent composable-scene worker."""

from __future__ import annotations

import os
from pathlib import Path

from manim_workbench_api.code_generation.repository import CodeGenerationRepository
from manim_workbench_api.code_generation.service import CodeGenerationService
from manim_workbench_api.content_plans.errors import ContentPlanError, ContentPlanErrorCode
from manim_workbench_api.content_plans.provider import DeepSeekProvider
from manim_workbench_api.content_plans.repository import ContentPlanRepository
from manim_workbench_api.content_plans.service import ContentPlanService
from manim_workbench_api.database import create_database_engine
from manim_workbench_api.jobs.repository import JobRepository
from manim_workbench_api.jobs.service import JobService
from manim_workbench_api.phase5_runtime import get_redis_job_signal_publisher
from manim_workbench_api.phase7_runtime import Phase7SandboxRenderer
from manim_workbench_api.program_rendering import ProgramQualityPolicy
from manim_workbench_api.projects.repository import ProjectRepository
from manim_workbench_api.workflows import (
    SceneBlockExecutor,
    ScientificSceneAdapter,
    TeachingSceneAdapter,
    WorkflowArtifactStore,
    WorkflowTaskQueue,
)
from manim_workbench_api.workflows.director.repository import DirectorRepository
from manim_workbench_api.workflows.director.service import DirectorPlanningService
from redis import Redis

from manim_workbench_runner.queue import (
    PersistentWorkflowTaskExecutor,
    PersistentWorkflowWorker,
    RedisWorkflowSignalQueue,
    SqliteWorkflowTaskLifecycle,
    WorkflowTaskCoordinator,
)
from manim_workbench_runner.rendering import CompositionResult


class WorkflowMediaQualityGate:
    """Program-level media floor after per-RenderJob diagnostics have already passed."""

    def evaluate(
        self,
        composition: CompositionResult,
        *,
        policy: ProgramQualityPolicy,
    ) -> tuple[str, ...]:
        del policy
        media = composition.media
        if media.frame_count <= 0 or not 0 < media.duration_seconds <= 600:
            return ("workflow_media_invalid",)
        return ()


class _UnavailableContentPlanProvider:
    def generate(self, messages):  # type: ignore[no-untyped-def]
        del messages
        raise ContentPlanError(
            ContentPlanErrorCode.CONFIGURATION_ERROR,
            "DeepSeek provider is not configured.",
        )


def build_workflow_worker(
    redis_client: Redis,
    *,
    runner_id: str,
) -> PersistentWorkflowWorker:
    """Build one worker over the same SQLite, Redis and artifact roots as API/Runner."""

    engine = create_database_engine()
    try:
        provider = DeepSeekProvider()
    except ContentPlanError:
        provider = None
    content_provider = provider or _UnavailableContentPlanProvider()
    projects = ProjectRepository(engine)
    content_plans = ContentPlanService(ContentPlanRepository(engine), content_provider)
    candidate_root = Path(
        os.environ.get(
            "MANIM_WORKBENCH_WORKFLOW_CANDIDATE_ROOT",
            "runtime/workflows/candidates",
        )
    )
    code_generation = CodeGenerationService(
        CodeGenerationRepository(engine),
        content_provider,
        Phase7SandboxRenderer(runtime_root=candidate_root),
    )
    scene_executor = SceneBlockExecutor(
        TeachingSceneAdapter(projects, content_plans, code_generation),
        ScientificSceneAdapter(
            projects,
            compute_root=Path(
                os.environ.get(
                    "MANIM_WORKBENCH_COMPUTE_ROOT", "runtime/compute-artifacts"
                )
            ),
            provider=provider,
        ),
    )
    artifact_root = Path(
        os.environ.get("MANIM_WORKBENCH_ARTIFACT_ROOT", "runtime/phase5/artifacts")
    )
    staging_root = Path(
        os.environ.get(
            "MANIM_WORKBENCH_WORKFLOW_STAGING_ROOT",
            "runtime/workflows/staging",
        )
    )
    artifact_store = WorkflowArtifactStore(engine, artifact_root, staging_root)
    executor = PersistentWorkflowTaskExecutor(
        engine,
        scene_executor,
        JobService(JobRepository(engine), get_redis_job_signal_publisher()),
        WorkflowMediaQualityGate(),
        artifact_store,
        render_artifact_root=artifact_root,
        workflow_staging_root=staging_root,
        composer_version="workflow-mvp-v1",
        director_service=DirectorPlanningService(
            DirectorRepository(engine), content_provider
        ),
    )
    coordinator = WorkflowTaskCoordinator(
        SqliteWorkflowTaskLifecycle(WorkflowTaskQueue(engine)),
        executor,
        runner_id=runner_id,
        lease_seconds=60,
    )
    return PersistentWorkflowWorker(
        RedisWorkflowSignalQueue(redis_client), coordinator
    )
