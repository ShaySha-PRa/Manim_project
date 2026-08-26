"""Persistent execution of scene-program and workflow-composition tasks."""

from __future__ import annotations

import hashlib
import re
import shutil
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from manim_workbench_api.assets.versions import load_asset_payloads
from manim_workbench_api.compiler.base import CompiledProgram, CompiledSegment
from manim_workbench_api.program_rendering import (
    JobProgramRenderBackend,
    ProgramArtifactPublisher,
    ProgramJobSubmitter,
    ProgramPublicationService,
    ProgramQualityGate,
    ProgramQualityPolicy,
    ProgramRenderRequest,
    ProgramRenderStatus,
    RenderedSegment,
    SegmentRenderEvidence,
    TypedProgramSegmentStore,
    program_sha256,
)
from manim_workbench_api.workflows import (
    ProgramRenderSource,
    ProgramRenderStore,
    SceneBlockExecutor,
    SceneCacheService,
    WorkflowArtifactStore,
    WorkflowClipEvidence,
    WorkflowComposer,
    WorkflowRepository,
    WorkflowTaskKind,
    WorkflowTaskQueue,
    build_composition_manifest,
)
from manim_workbench_api.workflows.composition import WorkflowArtifactPublisher
from manim_workbench_contracts import (
    CompositionManifest,
    CompositionRunStatus,
    ProgramRenderRun,
    ProgramRenderRunStatus,
    ProgramRenderSegment,
    RenderJobStatus,
    RenderProfile,
    SceneBlockRun,
    SceneBlockRunStatus,
    ScenePipeline,
    VideoWorkflowVersion,
)
from sqlalchemy import Engine, text

from manim_workbench_runner.rendering import ClipInput, CompositionResult, inspect_clip

from .workflow_coordinator import (
    WorkflowTaskExecution,
    WorkflowTaskLease,
)

_SCENE_CLASS = re.compile(r"^class\s+([A-Z][A-Za-z0-9]{1,99})\s*\(", re.MULTILINE)
_SCENE_TERMINAL = {
    SceneBlockRunStatus.SUCCEEDED,
    SceneBlockRunStatus.FAILED,
    SceneBlockRunStatus.NEEDS_CONFIRMATION,
    SceneBlockRunStatus.ASSET_REQUIRED,
}
_COMPOSITION_TERMINAL = {
    CompositionRunStatus.SUCCEEDED,
    CompositionRunStatus.FAILED,
    CompositionRunStatus.NOT_READY,
}


class SqliteWorkflowTaskLifecycle:
    """Adapt the SQLite-authoritative API queue to the Runner coordinator port."""

    def __init__(
        self,
        queue: WorkflowTaskQueue,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._queue = queue
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def claim(
        self, kind: str, *, runner_id: str, lease_seconds: int
    ) -> WorkflowTaskLease | None:
        task = self._queue.claim(
            WorkflowTaskKind(kind),
            worker_id=runner_id,
            lease_seconds=lease_seconds,
            now=self._clock(),
        )
        if task is None:
            return None
        if task.lease_token is None:
            raise ValueError("claimed workflow task is missing its lease token")
        return WorkflowTaskLease(
            task_id=task.id,
            run_id=task.run_id,
            project_id=task.project_id,
            owner_id=task.owner_id,
            kind=task.kind.value,
            lease_token=task.lease_token,
            attempt_count=task.attempt_count,
            payload=task.payload,
        )

    def complete(self, task_id: UUID, lease_token: str) -> bool:
        return self._queue.complete(task_id, lease_token, now=self._clock())

    def release(self, task_id: UUID, lease_token: str, *, retry_at: datetime) -> bool:
        return self._queue.release(
            task_id,
            lease_token,
            retry_at=retry_at,
            now=self._clock(),
        )


class PersistentWorkflowTaskExecutor:
    """Advance durable workflow stages without holding a lease while RenderJobs run."""

    def __init__(
        self,
        engine: Engine,
        scene_executor: SceneBlockExecutor,
        jobs: ProgramJobSubmitter,
        quality_gate: ProgramQualityGate,
        workflow_artifacts: WorkflowArtifactStore,
        *,
        render_artifact_root: Path,
        workflow_staging_root: Path,
        composer_version: str,
        retry_seconds: int = 5,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1 <= retry_seconds <= 300:
            raise ValueError("workflow retry seconds must be in the range [1, 300]")
        if not composer_version:
            raise ValueError("composer_version cannot be empty")
        if render_artifact_root.is_symlink() or workflow_staging_root.is_symlink():
            raise ValueError("workflow execution roots cannot be symlinks")
        render_artifact_root.mkdir(parents=True, exist_ok=True)
        workflow_staging_root.mkdir(parents=True, exist_ok=True)
        self._engine = engine
        self._repository = WorkflowRepository(engine)
        self._programs = ProgramRenderStore(engine)
        self._scene_executor = scene_executor
        self._jobs = jobs
        self._quality_gate = quality_gate
        self._workflow_artifacts = workflow_artifacts
        self._render_artifact_root = render_artifact_root.resolve(strict=True)
        self._staging_root = workflow_staging_root.resolve(strict=True)
        self._composer_version = composer_version
        self._retry_seconds = retry_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def execute(self, lease: WorkflowTaskLease) -> WorkflowTaskExecution | None:
        if lease.kind == WorkflowTaskKind.SCENE_PROGRAM.value:
            return self._execute_scene(lease)
        if lease.kind == WorkflowTaskKind.COMPOSITION.value:
            return self._execute_composition(lease)
        raise ValueError("unsupported workflow task kind")

    def _execute_scene(self, lease: WorkflowTaskLease) -> WorkflowTaskExecution | None:
        profile = self._profile(lease.payload)
        run = self._repository.get_scene_block_run(
            lease.run_id, lease.project_id, lease.owner_id
        )
        if run.status in _SCENE_TERMINAL:
            return None
        block_id = self._payload_uuid(lease.payload, "scene_block_version_id")
        workflow_id = self._payload_uuid(lease.payload, "workflow_version_id")
        if block_id != run.scene_block_version_id:
            raise ValueError("scene task block identity differs")
        block = self._repository.get_scene_block_version(
            block_id, lease.project_id, lease.owner_id
        )
        workflow = self._repository.get_workflow_version(
            workflow_id, lease.project_id, lease.owner_id
        )
        if block.workflow_id != workflow.workflow_id:
            raise ValueError("scene task workflow identity differs")

        stored_artifact = self._workflow_artifacts.find_for_run(
            project_id=lease.project_id,
            owner_id=lease.owner_id,
            profile=profile,
            scene_block_run_id=run.id,
        )
        found = self._programs.find(run.id, lease.project_id, lease.owner_id, profile)
        if stored_artifact is not None:
            self._workflow_artifacts.verified_path(stored_artifact)
            pipeline = self._pipeline_for(run.pipeline_used, found)
            if found is not None:
                self._programs.finish(found[0].id)
            self._append_scene_success(run, pipeline, profile, stored_artifact.id)
            return None
        cached_run = self._repository.find_scene_cache_source_run(
            run.cache_key, lease.project_id, lease.owner_id, profile
        )
        cache_hit = SceneCacheService(
            self._repository,
            artifact_root=self._workflow_artifacts.artifact_root,
            media_probe=lambda path: self._cache_media_valid(path, profile),
        ).lookup(
            run.cache_key,
            owner_id=lease.owner_id,
            project_id=lease.project_id,
            profile=profile,
        )
        if cached_run is not None and cache_hit is not None:
            source_id = (
                cached_run.preview_artifact_id
                if profile is RenderProfile.PREVIEW
                else cached_run.final_artifact_id
            )
            if source_id is None:
                raise ValueError("cache source artifact reference is missing")
            source = self._workflow_artifacts.get(
                source_id,
                project_id=lease.project_id,
                owner_id=lease.owner_id,
            )
            if source is None:
                raise ValueError("cache source artifact disappeared")
            reused = self._workflow_artifacts.reuse(source, scene_block_run_id=run.id)
            self._append_scene_success(
                run,
                self._pipeline_for(cached_run.pipeline_used, None),
                profile,
                reused.id,
                intent_ref=cached_run.intent_ref,
                animation_ir_ref=cached_run.animation_ir_ref,
                compiled_program_ref=cached_run.compiled_program_ref,
            )
            return None
        if found is not None and found[0].status is ProgramRenderRunStatus.FAILED:
            self._append_scene_failure(
                run, found[0].failure_code or "program_render_failed"
            )
            return None

        if run.status is SceneBlockRunStatus.QUEUED:
            run = self._repository.append_scene_block_run_event(
                run_id=run.id,
                project_id=lease.project_id,
                owner_id=lease.owner_id,
                expected_state_version=run.state_version,
                status=SceneBlockRunStatus.PLANNING,
            )

        if found is None:
            assets = load_asset_payloads(
                self._engine,
                block.asset_version_ids,
                owner_id=lease.owner_id,
                project_id=lease.project_id,
            )
            csv_text = next(
                (asset.text for asset in assets if asset.mime == "text/csv"), None
            )
            paper_text = next(
                (asset.text for asset in assets if asset.mime == "text/plain"), None
            )
            preparation = self._scene_executor.prepare(
                block,
                workflow.global_brief,
                csv_text=csv_text,
                paper_text=paper_text,
                previous_scene_summary=self._payload_text(
                    lease.payload, "previous_scene_summary"
                ),
            )
            if preparation.compilation is None or preparation.pipeline is None:
                self._repository.append_scene_block_run_event(
                    run_id=run.id,
                    project_id=lease.project_id,
                    owner_id=lease.owner_id,
                    expected_state_version=run.state_version,
                    status=preparation.status,
                    pipeline_used=preparation.pipeline,
                    error_code=preparation.error_code,
                )
                return None
            compilation = preparation.compilation
            intent_ref, animation_ir_ref = self._repository.persist_scene_provenance(
                run_id=run.id,
                project_id=lease.project_id,
                owner_id=lease.owner_id,
                intent=compilation.intent,
                animation_ir=compilation.animation_ir,
                tool_runs=compilation.tool_runs,
                provenance=compilation.provenance,
            )
            digest = program_sha256(compilation.program)
            sources = tuple(
                self._program_source(segment) for segment in compilation.program.segments
            )
            found = self._programs.create_or_get(
                scene_block_run_id=run.id,
                project_id=lease.project_id,
                owner_id=lease.owner_id,
                profile=profile,
                program_sha256=digest,
                quality_policy=preparation.pipeline.value,
                segment_sources=sources,
            )
            run = self._repository.append_scene_block_run_event(
                run_id=run.id,
                project_id=lease.project_id,
                owner_id=lease.owner_id,
                expected_state_version=run.state_version,
                status=SceneBlockRunStatus.COMPILING,
                pipeline_used=preparation.pipeline,
                intent_ref=intent_ref,
                animation_ir_ref=animation_ir_ref,
                compiled_program_ref=found[0].id,
            )

        program_run, segments = found
        sources = self._programs.load_sources(
            program_run.id, lease.project_id, lease.owner_id
        )
        program = self._rehydrate_program(sources)
        request = self._program_request(program_run, program)
        backend = JobProgramRenderBackend(
            TypedProgramSegmentStore(
                segments,
                lambda index, job_id: self._programs.attach_job(
                    program_run.id, index, job_id
                ),
            ),
            self._jobs,
        )
        backend.submit(request)
        program_run, segments = self._require_program(run.id, profile, lease)
        if run.status is not SceneBlockRunStatus.RENDERING:
            run = self._repository.append_scene_block_run_event(
                run_id=run.id,
                project_id=lease.project_id,
                owner_id=lease.owner_id,
                expected_state_version=run.state_version,
                status=SceneBlockRunStatus.RENDERING,
                pipeline_used=self._pipeline_for(run.pipeline_used, found),
                intent_ref=run.intent_ref,
                animation_ir_ref=run.animation_ir_ref,
                compiled_program_ref=program_run.id,
            )
        evidence, active, failure_code = self._collect_segment_evidence(
            program_run.id, segments, profile
        )
        if failure_code is not None:
            self._programs.finish(program_run.id, failure_code=failure_code)
            self._append_scene_failure(run, failure_code)
            return None
        if active:
            return WorkflowTaskExecution(
                retry_at=self._clock() + timedelta(seconds=self._retry_seconds)
            )

        self._programs.mark_composing(program_run.id)
        publisher = _SceneProgramPublisher(
            self._workflow_artifacts,
            self._staging_root,
            run_id=run.id,
            project_id=lease.project_id,
            owner_id=lease.owner_id,
            profile=profile,
        )
        result = ProgramPublicationService(self._quality_gate, publisher).finalize(
            request,
            evidence,
            output=self._staging_file("scene-compose", run.id, profile),
            staging_root=self._staging_root,
        )
        if result.status is not ProgramRenderStatus.SUCCEEDED or result.artifact_id is None:
            failure = result.failure_code or "program_publish_failed"
            self._programs.finish(program_run.id, failure_code=failure)
            self._append_scene_failure(run, failure)
            return None
        self._programs.finish(program_run.id)
        self._append_scene_success(
            run,
            self._pipeline_for(run.pipeline_used, found),
            profile,
            result.artifact_id,
        )
        return None

    def _execute_composition(
        self, lease: WorkflowTaskLease
    ) -> WorkflowTaskExecution | None:
        profile = self._profile(lease.payload)
        run = self._repository.get_composition_run(
            lease.run_id, lease.project_id, lease.owner_id
        )
        if run.status in _COMPOSITION_TERMINAL:
            return None
        workflow_id = self._payload_uuid(lease.payload, "workflow_version_id")
        if workflow_id != run.workflow_version_id:
            raise ValueError("composition task workflow identity differs")
        workflow = self._repository.get_workflow_version(
            workflow_id, lease.project_id, lease.owner_id
        )
        rows = self._repository.get_composition_clip_rows(workflow, profile)
        if rows is None:
            self._repository.append_composition_run_event(
                run_id=run.id,
                project_id=lease.project_id,
                owner_id=lease.owner_id,
                expected_state_version=run.state_version,
                status=CompositionRunStatus.NOT_READY,
                error_code="scene_clips_not_ready",
            )
            return None
        manifest = self._manifest(workflow, profile, rows)
        stored_artifact = self._workflow_artifacts.find_for_run(
            project_id=lease.project_id,
            owner_id=lease.owner_id,
            profile=profile,
            composition_run_id=run.id,
        )
        if stored_artifact is not None:
            self._workflow_artifacts.verified_path(stored_artifact)
            self._repository.append_composition_run_event(
                run_id=run.id,
                project_id=lease.project_id,
                owner_id=lease.owner_id,
                expected_state_version=run.state_version,
                status=CompositionRunStatus.SUCCEEDED,
                manifest=manifest,
                artifact_id=stored_artifact.id,
            )
            return None
        cached_run = self._repository.find_composition_cache_source_run(
            run.cache_key, lease.project_id, lease.owner_id, profile
        )
        if cached_run is not None and cached_run.artifact_id is not None:
            source = self._workflow_artifacts.get(
                cached_run.artifact_id,
                project_id=lease.project_id,
                owner_id=lease.owner_id,
            )
            if source is not None:
                reused = self._workflow_artifacts.reuse(
                    source, composition_run_id=run.id
                )
                self._repository.append_composition_run_event(
                    run_id=run.id,
                    project_id=lease.project_id,
                    owner_id=lease.owner_id,
                    expected_state_version=run.state_version,
                    status=CompositionRunStatus.SUCCEEDED,
                    manifest=manifest,
                    artifact_id=reused.id,
                )
                return None
        if run.status is CompositionRunStatus.QUEUED:
            run = self._repository.append_composition_run_event(
                run_id=run.id,
                project_id=lease.project_id,
                owner_id=lease.owner_id,
                expected_state_version=run.state_version,
                status=CompositionRunStatus.COMPOSING,
            )
        clips = tuple(self._workflow_clip(row, workflow, profile) for row in rows)
        publisher = _CompositionPublisher(
            self._workflow_artifacts,
            self._staging_root,
            run_id=run.id,
            project_id=lease.project_id,
            owner_id=lease.owner_id,
            profile=profile,
        )
        result = WorkflowComposer(
            publisher, composer_version=self._composer_version
        ).compose(
            workflow,
            profile=profile,
            clips=clips,
            output=self._staging_file("workflow-compose", run.id, profile),
            staging_root=self._staging_root,
        )
        if not result.succeeded or result.artifact_id is None or result.manifest is None:
            self._repository.append_composition_run_event(
                run_id=run.id,
                project_id=lease.project_id,
                owner_id=lease.owner_id,
                expected_state_version=run.state_version,
                status=CompositionRunStatus.FAILED,
                error_code=result.failure_code or "composition_failed",
            )
            return None
        self._repository.append_composition_run_event(
            run_id=run.id,
            project_id=lease.project_id,
            owner_id=lease.owner_id,
            expected_state_version=run.state_version,
            status=CompositionRunStatus.SUCCEEDED,
            manifest=result.manifest,
            artifact_id=result.artifact_id,
        )
        return None

    def _collect_segment_evidence(
        self,
        program_run_id: UUID,
        segments: tuple[ProgramRenderSegment, ...],
        profile: RenderProfile,
    ) -> tuple[tuple[SegmentRenderEvidence, ...], bool, str | None]:
        evidence: list[SegmentRenderEvidence] = []
        active = False
        failure_code: str | None = None
        with self._engine.connect() as connection:
            for segment in segments:
                if segment.render_job_id is None:
                    active = True
                    evidence.append(
                        SegmentRenderEvidence(
                            RenderedSegment(
                                segment_index=segment.segment_index,
                                source_sha256=segment.source_sha256,
                                status=ProgramRenderStatus.QUEUED,
                            ),
                            None,
                        )
                    )
                    continue
                job = (
                    connection.execute(
                        text(
                            "SELECT status,failure_code FROM render_jobs WHERE id=:job "
                            "AND program_render_segment_id=:segment"
                        ),
                        {"job": str(segment.render_job_id), "segment": str(segment.id)},
                    )
                    .mappings()
                    .one_or_none()
                )
                if job is None:
                    raise ValueError("program segment RenderJob identity differs")
                status = RenderJobStatus(str(job["status"]))
                if status in {RenderJobStatus.FAILED, RenderJobStatus.CANCELLED}:
                    code = str(job["failure_code"] or "render_job_cancelled")
                    self._programs.record_segment_failure(
                        program_run_id, segment.segment_index, code
                    )
                    failure_code = failure_code or "segment_failed"
                    rendered = RenderedSegment(
                        segment_index=segment.segment_index,
                        source_sha256=segment.source_sha256,
                        status=ProgramRenderStatus.FAILED,
                        render_job_id=segment.render_job_id,
                        failure_code=code,
                    )
                    evidence.append(SegmentRenderEvidence(rendered, None))
                    continue
                if status is not RenderJobStatus.SUCCEEDED:
                    active = True
                    rendered = RenderedSegment(
                        segment_index=segment.segment_index,
                        source_sha256=segment.source_sha256,
                        status=(
                            ProgramRenderStatus.QUEUED
                            if status is RenderJobStatus.QUEUED
                            else ProgramRenderStatus.RENDERING
                        ),
                        render_job_id=segment.render_job_id,
                    )
                    evidence.append(SegmentRenderEvidence(rendered, None))
                    continue
                artifact = (
                    connection.execute(
                        text(
                            "SELECT id,relative_path,sha256,byte_size FROM artifacts "
                            "WHERE render_job_id=:job AND kind='video'"
                        ),
                        {"job": str(segment.render_job_id)},
                    )
                    .mappings()
                    .one_or_none()
                )
                if artifact is None:
                    raise ValueError("succeeded RenderJob is missing its video artifact")
                artifact_id = UUID(str(artifact["id"]))
                digest = str(artifact["sha256"])
                self._programs.record_segment_artifact(
                    program_run_id,
                    segment.segment_index,
                    artifact_id=artifact_id,
                    artifact_sha256=digest,
                )
                path = self._render_path(str(artifact["relative_path"]))
                if path.stat().st_size != int(artifact["byte_size"]):
                    raise ValueError("render artifact size differs")
                rendered = RenderedSegment(
                    segment_index=segment.segment_index,
                    source_sha256=segment.source_sha256,
                    status=ProgramRenderStatus.SUCCEEDED,
                    render_job_id=segment.render_job_id,
                    artifact_id=artifact_id,
                    artifact_sha256=digest,
                )
                evidence.append(
                    SegmentRenderEvidence(
                        rendered,
                        ClipInput(path=path, profile=profile, sha256=digest),
                    )
                )
        return tuple(evidence), active, failure_code

    def _workflow_clip(
        self,
        row: dict[str, object],
        workflow: VideoWorkflowVersion,
        profile: RenderProfile,
    ) -> WorkflowClipEvidence:
        artifact_id = UUID(str(row["artifact_id"]))
        artifact = self._workflow_artifacts.get(
            artifact_id,
            project_id=workflow.project_id,
            owner_id=workflow.owner_id,
        )
        if artifact is None or artifact.profile is not profile:
            raise ValueError("workflow clip artifact identity differs")
        return WorkflowClipEvidence(
            scene_block_version_id=UUID(str(row["scene_block_version_id"])),
            artifact_id=artifact.id,
            owner_id=artifact.owner_id,
            project_id=artifact.project_id,
            profile=artifact.profile,
            path=self._workflow_artifacts.verified_path(artifact),
            artifact_sha256=artifact.sha256,
            byte_size=artifact.byte_size,
            intent_ref=self._row_uuid(row, "intent_ref"),
            animation_ir_ref=self._row_uuid(row, "animation_ir_ref"),
            compiled_program_ref=self._row_uuid(row, "compiled_program_ref"),
        )

    def _append_scene_success(
        self,
        run: SceneBlockRun,
        pipeline: ScenePipeline,
        profile: RenderProfile,
        artifact_id: UUID,
        *,
        intent_ref: UUID | None = None,
        animation_ir_ref: UUID | None = None,
        compiled_program_ref: UUID | None = None,
    ) -> None:
        current = self._repository.get_scene_block_run(
            run.id, run.project_id, run.owner_id
        )
        if current.status is SceneBlockRunStatus.SUCCEEDED:
            return
        values = {
            "preview_artifact_id": artifact_id
            if profile is RenderProfile.PREVIEW
            else None,
            "final_artifact_id": artifact_id if profile is RenderProfile.FINAL else None,
        }
        self._repository.append_scene_block_run_event(
            run_id=current.id,
            project_id=current.project_id,
            owner_id=current.owner_id,
            expected_state_version=current.state_version,
            status=SceneBlockRunStatus.SUCCEEDED,
            pipeline_used=pipeline,
            intent_ref=intent_ref or current.intent_ref,
            animation_ir_ref=animation_ir_ref or current.animation_ir_ref,
            compiled_program_ref=compiled_program_ref or current.compiled_program_ref,
            **values,
        )

    def _append_scene_failure(self, run: SceneBlockRun, failure_code: str) -> None:
        current = self._repository.get_scene_block_run(
            run.id, run.project_id, run.owner_id
        )
        if current.status in _SCENE_TERMINAL:
            return
        self._repository.append_scene_block_run_event(
            run_id=current.id,
            project_id=current.project_id,
            owner_id=current.owner_id,
            expected_state_version=current.state_version,
            status=SceneBlockRunStatus.FAILED,
            pipeline_used=current.pipeline_used,
            intent_ref=current.intent_ref,
            animation_ir_ref=current.animation_ir_ref,
            compiled_program_ref=current.compiled_program_ref,
            error_code=failure_code,
        )

    def _require_program(
        self,
        scene_run_id: UUID,
        profile: RenderProfile,
        lease: WorkflowTaskLease,
    ) -> tuple[ProgramRenderRun, tuple[ProgramRenderSegment, ...]]:
        found = self._programs.find(
            scene_run_id, lease.project_id, lease.owner_id, profile
        )
        if found is None:
            raise ValueError("program render run disappeared")
        return found

    @staticmethod
    def _program_source(segment: CompiledSegment) -> ProgramRenderSource:
        matched = _SCENE_CLASS.search(segment.source)
        if matched is None:
            raise ValueError("compiled segment is missing a concrete Scene class")
        return ProgramRenderSource(
            source_code=segment.source,
            source_sha256=hashlib.sha256(segment.source.encode("utf-8")).hexdigest(),
            scene_class=matched.group(1),
            target_duration_seconds=segment.duration_seconds,
        )

    @staticmethod
    def _rehydrate_program(sources: tuple[ProgramRenderSource, ...]) -> CompiledProgram:
        return CompiledProgram(
            segments=tuple(
                CompiledSegment(
                    source=source.source_code,
                    scene_base="Scene",
                    visual_kinds=(),
                    duration_seconds=source.target_duration_seconds,
                )
                for source in sources
            )
        )

    @staticmethod
    def _program_request(
        program_run: ProgramRenderRun, program: CompiledProgram
    ) -> ProgramRenderRequest:
        deadline = min(
            3_600,
            max(5, int(sum(item.duration_seconds for item in program.segments) * 4 + 60)),
        )
        return ProgramRenderRequest(
            owner_id=program_run.owner_id,
            project_id=program_run.project_id,
            program=program,
            program_sha256=program_run.program_sha256,
            profile=program_run.profile,
            idempotency_key=hashlib.sha256(
                f"workflow-program:{program_run.id}:{program_run.program_sha256}".encode()
            ).hexdigest(),
            deadline_seconds=deadline,
            quality_policy=ProgramQualityPolicy(program_run.quality_policy),
        )

    @staticmethod
    def _pipeline_for(
        run_pipeline: ScenePipeline | None,
        found: tuple[ProgramRenderRun, tuple[ProgramRenderSegment, ...]] | None,
    ) -> ScenePipeline:
        if run_pipeline is not None:
            return run_pipeline
        if found is None:
            raise ValueError("scene pipeline evidence is missing")
        return ScenePipeline(found[0].quality_policy)

    def _render_path(self, relative_path: str) -> Path:
        candidate = PurePosixPath(relative_path.replace("\\", "/"))
        if not relative_path or candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("render artifact path is unsafe")
        path = self._render_artifact_root
        for part in candidate.parts:
            path = path / part
            if path.is_symlink():
                raise ValueError("render artifact path contains a symlink")
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(self._render_artifact_root) or not resolved.is_file():
            raise ValueError("render artifact path escaped its root")
        return resolved

    def _staging_file(self, prefix: str, run_id: UUID, profile: RenderProfile) -> Path:
        return self._staging_root / f"{prefix}-{run_id}-{profile.value}-{uuid4().hex}.mp4"

    def _manifest(
        self,
        workflow: VideoWorkflowVersion,
        profile: RenderProfile,
        rows: tuple[dict[str, object], ...],
    ) -> CompositionManifest:
        from manim_workbench_api.workflows import SceneClipDescriptor

        return build_composition_manifest(
            workflow,
            profile=profile,
            clips=tuple(
                SceneClipDescriptor(
                    scene_block_version_id=UUID(str(row["scene_block_version_id"])),
                    artifact_sha256=str(row["sha256"]),
                    duration_seconds=float(row["duration_seconds"]),
                    intent_ref=self._row_uuid(row, "intent_ref"),
                    animation_ir_ref=self._row_uuid(row, "animation_ir_ref"),
                    compiled_program_ref=self._row_uuid(row, "compiled_program_ref"),
                )
                for row in rows
            ),
            composer_version=self._composer_version,
        )

    @staticmethod
    def _profile(payload: dict[str, object]) -> RenderProfile:
        return RenderProfile(str(payload.get("profile", "")))

    @staticmethod
    def _payload_uuid(payload: dict[str, object], key: str) -> UUID:
        try:
            return UUID(str(payload[key]))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"workflow task {key} is invalid") from error

    @staticmethod
    def _row_uuid(row: dict[str, object], key: str) -> UUID | None:
        value = row.get(key)
        return UUID(str(value)) if value is not None else None

    @staticmethod
    def _payload_text(payload: dict[str, object], key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise ValueError(f"workflow task {key} is invalid")
        return value

    @staticmethod
    def _cache_media_valid(path: Path, profile: RenderProfile) -> bool:
        try:
            inspect_clip(
                ClipInput(path, profile, hashlib.sha256(path.read_bytes()).hexdigest())
            )
        except (OSError, ValueError):
            return False
        return True


class _SceneProgramPublisher(ProgramArtifactPublisher):
    def __init__(
        self,
        store: WorkflowArtifactStore,
        staging_root: Path,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        profile: RenderProfile,
    ) -> None:
        self._store = store
        self._staging_root = staging_root
        self._run_id = run_id
        self._project_id = project_id
        self._owner_id = owner_id
        self._profile = profile

    def publish(
        self, request: ProgramRenderRequest, composition: CompositionResult
    ) -> UUID:
        if request.profile is not self._profile:
            raise ValueError("program publication profile differs")
        source = composition.path
        if composition.reused_single_clip:
            copied = self._staging_root / f"scene-publish-{self._run_id}-{uuid4().hex}.mp4"
            shutil.copyfile(source, copied)
            source = copied
        return self._store.publish(
            source,
            project_id=self._project_id,
            owner_id=self._owner_id,
            profile=self._profile,
            duration_seconds=composition.media.duration_seconds,
            scene_block_run_id=self._run_id,
        ).id


class _CompositionPublisher(WorkflowArtifactPublisher):
    def __init__(
        self,
        store: WorkflowArtifactStore,
        staging_root: Path,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        profile: RenderProfile,
    ) -> None:
        self._store = store
        self._staging_root = staging_root
        self._run_id = run_id
        self._project_id = project_id
        self._owner_id = owner_id
        self._profile = profile

    def publish(
        self,
        workflow: VideoWorkflowVersion,
        manifest: CompositionManifest,
        composition: CompositionResult,
    ) -> UUID:
        if (
            workflow.project_id != self._project_id
            or workflow.owner_id != self._owner_id
            or manifest.profile is not self._profile
        ):
            raise ValueError("composition publication identity differs")
        source = composition.path
        if composition.reused_single_clip:
            copied = self._staging_root / f"composition-publish-{self._run_id}-{uuid4().hex}.mp4"
            shutil.copyfile(source, copied)
            source = copied
        return self._store.publish(
            source,
            project_id=self._project_id,
            owner_id=self._owner_id,
            profile=self._profile,
            duration_seconds=composition.media.duration_seconds,
            composition_run_id=self._run_id,
        ).id
