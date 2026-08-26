from __future__ import annotations

import hashlib
from uuid import UUID

from manim_workbench_contracts import (
    CompositionRun,
    CompositionRunStatus,
    SceneBlockRun,
    ScenePipeline,
    ScenePipelineMode,
    VideoWorkflowVersion,
)
from sqlalchemy import Engine, text

from manim_workbench_api.assets.scientific import ingest_csv_text
from manim_workbench_api.assets.versions import persist_asset_version

from .cache import SceneCacheVersions, canonical_json, scene_cache_key
from .composition import (
    SceneClipDescriptor,
    build_composition_manifest,
    composition_cache_key,
)
from .executor import preflight_scene, route_scene_pipeline
from .models import (
    CompositionRunCreateRequest,
    SceneBlockCreateRequest,
    SceneBlockCreation,
    SceneBlockVersionCreateRequest,
    SceneRunCreateRequest,
    ScientificAssetRecord,
    WorkflowVersionCreateRequest,
)
from .queue import WorkflowTaskKind, WorkflowTaskNotifier, WorkflowTaskQueue
from .repository import WorkflowRepository

SCENE_CACHE_VERSIONS = SceneCacheVersions(
    pipeline="workflow-mvp-v1",
    template="teaching-storyboard-v1+intent-v1",
    tool="scientific-tools-v2",
    compiler="compiled-program-v1",
    renderer="manimce-0.21.0",
)
COMPOSER_VERSION = "workflow-mvp-v1"


class WorkflowService:
    def __init__(
        self, engine: Engine, notifier: WorkflowTaskNotifier | None = None
    ) -> None:
        self._engine = engine
        self._repository = WorkflowRepository(engine)
        self._queue = WorkflowTaskQueue(engine, notifier)

    @property
    def repository(self) -> WorkflowRepository:
        return self._repository

    def create_scene_block(
        self,
        workflow_id: UUID,
        owner_id: UUID,
        request: SceneBlockCreateRequest,
    ) -> SceneBlockCreation:
        workflow = self._repository.get_workflow(workflow_id, owner_id)
        block, version = self._repository.create_scene_block_record(
            workflow_id=workflow_id,
            project_id=workflow.project_id,
            owner_id=owner_id,
            **request.model_dump(),
        )
        return SceneBlockCreation(block=block, version=version)

    def create_csv_asset(
        self, project_id: UUID, owner_id: UUID, csv_text: str
    ) -> ScientificAssetRecord:
        with self._engine.connect() as connection:
            active = connection.execute(
                text(
                    "SELECT id FROM projects WHERE id=:project_id AND owner_id=:owner_id "
                    "AND archived_at IS NULL"
                ),
                {"project_id": str(project_id), "owner_id": str(owner_id)},
            ).scalar_one_or_none()
        if active is None:
            from .errors import WORKFLOW_NOT_FOUND

            raise WORKFLOW_NOT_FOUND
        asset = ingest_csv_text(csv_text)
        asset_id = persist_asset_version(
            self._engine,
            asset,
            owner_id=owner_id,
            project_id=project_id,
            payload_text=csv_text,
        )
        return ScientificAssetRecord(
            id=asset_id,
            project_id=project_id,
            owner_id=owner_id,
            sha256=asset.sha256,
            mime=asset.mime.value,
            size_bytes=asset.size_bytes,
        )

    def append_scene_block_version(
        self,
        block_id: UUID,
        owner_id: UUID,
        request: SceneBlockVersionCreateRequest,
    ):
        block = self._repository.get_scene_block(block_id, owner_id)
        return self._repository.append_scene_block_version(
            scene_block_id=block_id,
            project_id=block.project_id,
            owner_id=owner_id,
            **request.model_dump(),
        )

    def append_workflow_version(
        self,
        workflow_id: UUID,
        owner_id: UUID,
        request: WorkflowVersionCreateRequest,
    ) -> VideoWorkflowVersion:
        workflow = self._repository.get_workflow(workflow_id, owner_id)
        return self._repository.append_workflow_version(
            workflow_id=workflow_id,
            project_id=workflow.project_id,
            owner_id=owner_id,
            parent_version_id=request.parent_version_id,
            global_brief=request.global_brief,
            nodes=request.nodes,
            edges=request.edges,
        )

    def submit_scene_run(
        self,
        version_id: UUID,
        owner_id: UUID,
        request: SceneRunCreateRequest,
    ) -> SceneBlockRun:
        block = self._repository.get_scene_block_version(
            version_id,
            self._project_for_workflow_version(request.workflow_version_id, owner_id),
            owner_id,
        )
        workflow = self._repository.get_workflow_version(
            request.workflow_version_id, block.project_id, owner_id
        )
        if workflow.workflow_id != block.workflow_id:
            from .errors import WORKFLOW_REFERENCE_INVALID

            raise WORKFLOW_REFERENCE_INVALID
        existing = self._repository.find_scene_run_by_idempotency(
            request.idempotency_key, block.project_id, owner_id
        )
        if existing is not None:
            return existing
        pipeline = self._pipeline(block.pipeline_mode, block.prompt)
        key_pipeline = pipeline or ScenePipeline.TEACHING
        asset_metadata = self._asset_metadata(
            block.asset_version_ids, block.project_id, owner_id
        )
        cache_key = scene_cache_key(
            block=block,
            global_brief=workflow.global_brief,
            asset_hashes=tuple(item[0] for item in asset_metadata),
            pipeline=key_pipeline,
            versions=SCENE_CACHE_VERSIONS,
            profile=request.profile,
        )
        run = self._repository.create_scene_block_run(
            scene_block_version_id=block.id,
            workflow_version_id=workflow.id,
            project_id=block.project_id,
            owner_id=owner_id,
            cache_key=cache_key,
            idempotency_key=request.idempotency_key,
            profile=request.profile,
        )
        stop = preflight_scene(
            block.prompt,
            pipeline,
            asset_mimes=tuple(item[1] for item in asset_metadata),
        )
        if stop is not None:
            status, error_code = stop
            return self._repository.append_scene_block_run_event(
                run_id=run.id,
                project_id=block.project_id,
                owner_id=owner_id,
                expected_state_version=0,
                status=status,
                pipeline_used=pipeline,
                error_code=error_code,
            )
        task = self._queue.submit(
            kind=WorkflowTaskKind.SCENE_PROGRAM,
            run_id=run.id,
            project_id=block.project_id,
            owner_id=owner_id,
            idempotency_key=request.idempotency_key,
            payload={
                "scene_block_version_id": str(block.id),
                "workflow_version_id": str(workflow.id),
                "profile": request.profile.value,
                "cache_key": cache_key,
            },
        )
        del task
        return run

    def submit_composition_run(
        self,
        workflow_version_id: UUID,
        owner_id: UUID,
        request: CompositionRunCreateRequest,
    ) -> CompositionRun:
        project_id = self._project_for_workflow_version(workflow_version_id, owner_id)
        workflow = self._repository.get_workflow_version(
            workflow_version_id, project_id, owner_id
        )
        existing = self._repository.find_composition_run_by_idempotency(
            request.idempotency_key, project_id, owner_id
        )
        if existing is not None:
            return existing
        rows = self._repository.get_composition_clip_rows(workflow, request.profile)
        if rows is None:
            cache_key = hashlib.sha256(
                canonical_json(
                    {
                        "workflow_version_id": workflow.id,
                        "profile": request.profile,
                        "state": "not_ready_to_compose",
                    }
                ).encode("utf-8")
            ).hexdigest()
        else:
            manifest = build_composition_manifest(
                workflow,
                profile=request.profile,
                clips=tuple(
                    SceneClipDescriptor(
                        scene_block_version_id=row["scene_block_version_id"],
                        artifact_sha256=str(row["sha256"]),
                        duration_seconds=float(row["duration_seconds"]),
                        intent_ref=row["intent_ref"],
                        animation_ir_ref=row["animation_ir_ref"],
                        compiled_program_ref=row["compiled_program_ref"],
                    )
                    for row in rows
                ),
                composer_version=COMPOSER_VERSION,
            )
            cache_key = composition_cache_key(workflow, manifest)
        run = self._repository.create_composition_run(
            workflow_version_id=workflow.id,
            project_id=project_id,
            owner_id=owner_id,
            profile=request.profile,
            cache_key=cache_key,
            idempotency_key=request.idempotency_key,
        )
        if rows is None:
            return self._repository.append_composition_run_event(
                run_id=run.id,
                project_id=project_id,
                owner_id=owner_id,
                expected_state_version=0,
                status=CompositionRunStatus.NOT_READY,
                error_code="scene_clips_not_ready",
            )
        self._queue.submit(
            kind=WorkflowTaskKind.COMPOSITION,
            run_id=run.id,
            project_id=project_id,
            owner_id=owner_id,
            idempotency_key=request.idempotency_key,
            payload={
                "workflow_version_id": str(workflow.id),
                "profile": request.profile.value,
                "cache_key": cache_key,
                "artifact_ids": [str(row["artifact_id"]) for row in rows],
            },
        )
        return run

    def get_workflow_version_for_owner(
        self, version_id: UUID, owner_id: UUID
    ) -> VideoWorkflowVersion:
        project_id = self._project_for_workflow_version(version_id, owner_id)
        return self._repository.get_workflow_version(version_id, project_id, owner_id)

    def get_scene_run_for_owner(self, run_id: UUID, owner_id: UUID) -> SceneBlockRun:
        project_id = self._project_for_run("scene_block_runs", run_id, owner_id)
        return self._repository.get_scene_block_run(run_id, project_id, owner_id)

    def get_composition_run_for_owner(
        self, run_id: UUID, owner_id: UUID
    ) -> CompositionRun:
        project_id = self._project_for_run(
            "workflow_composition_runs", run_id, owner_id
        )
        return self._repository.get_composition_run(run_id, project_id, owner_id)

    def _project_for_run(self, table: str, run_id: UUID, owner_id: UUID) -> UUID:
        if table not in {"scene_block_runs", "workflow_composition_runs"}:
            raise ValueError("unsupported workflow run table")
        with self._engine.connect() as connection:
            value = connection.execute(
                text(
                    f"SELECT r.project_id FROM {table} r JOIN projects p ON p.id=r.project_id "
                    f"WHERE r.id=:id AND r.owner_id=:owner_id AND p.owner_id=:owner_id "
                    f"AND p.archived_at IS NULL"
                ),
                {"id": str(run_id), "owner_id": str(owner_id)},
            ).scalar_one_or_none()
        if value is None:
            from .errors import WORKFLOW_NOT_FOUND

            raise WORKFLOW_NOT_FOUND
        return UUID(str(value))

    def _project_for_workflow_version(self, version_id: UUID, owner_id: UUID) -> UUID:
        with self._engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT v.project_id FROM video_workflow_versions v "
                    "JOIN projects p ON p.id=v.project_id WHERE v.id=:id "
                    "AND v.owner_id=:owner_id AND p.owner_id=:owner_id "
                    "AND p.archived_at IS NULL"
                ),
                {"id": str(version_id), "owner_id": str(owner_id)},
            ).scalar_one_or_none()
        if value is None:
            from .errors import WORKFLOW_NOT_FOUND

            raise WORKFLOW_NOT_FOUND
        return UUID(str(value))

    def _asset_metadata(
        self, asset_ids: tuple[UUID, ...], project_id: UUID, owner_id: UUID
    ) -> tuple[tuple[str, str], ...]:
        metadata: list[tuple[str, str]] = []
        with self._engine.connect() as connection:
            for asset_id in asset_ids:
                value = connection.execute(
                    text(
                        "SELECT sha256,mime FROM asset_versions WHERE id=:id "
                        "AND project_id=:project_id AND owner_id=:owner_id"
                    ),
                    {
                        "id": str(asset_id),
                        "project_id": str(project_id),
                        "owner_id": str(owner_id),
                    },
                ).one_or_none()
                if value is None:
                    from .errors import WORKFLOW_REFERENCE_INVALID

                    raise WORKFLOW_REFERENCE_INVALID
                metadata.append((str(value.sha256), str(value.mime)))
        return tuple(metadata)

    @staticmethod
    def _pipeline(mode: ScenePipelineMode, prompt: str) -> ScenePipeline | None:
        if mode is ScenePipelineMode.TEACHING:
            return ScenePipeline.TEACHING
        if mode is ScenePipelineMode.SCIENTIFIC:
            return ScenePipeline.SCIENTIFIC
        return route_scene_pipeline(prompt)
