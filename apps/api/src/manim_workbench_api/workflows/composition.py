from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from manim_workbench_contracts import (
    CompositionManifest,
    CompositionManifestClip,
    RenderProfile,
    VideoWorkflowVersion,
    WorkflowNodeKind,
)
from manim_workbench_runner.rendering import (
    ClipInput,
    CompositionResult,
    ConcatError,
    compose_mp4s,
    inspect_clip,
)

from .cache import canonical_json
from .validation import WorkflowValidationError


@dataclass(frozen=True, slots=True)
class SceneClipDescriptor:
    scene_block_version_id: UUID
    artifact_sha256: str
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class WorkflowClipEvidence:
    scene_block_version_id: UUID
    artifact_id: UUID
    owner_id: UUID
    project_id: UUID
    profile: RenderProfile
    path: Path
    artifact_sha256: str
    byte_size: int
    succeeded: bool = True


@dataclass(frozen=True, slots=True)
class WorkflowCompositionResult:
    succeeded: bool
    manifest: CompositionManifest | None = None
    artifact_id: UUID | None = None
    media_sha256: str | None = None
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowExecutionPlan:
    scene_indexes_to_run: tuple[int, ...]
    compose_required: bool


def plan_workflow_execution(
    scene_cache_hits: tuple[bool, ...], *, composition_cache_hit: bool
) -> WorkflowExecutionPlan:
    missing = tuple(index for index, hit in enumerate(scene_cache_hits) if not hit)
    return WorkflowExecutionPlan(
        scene_indexes_to_run=missing,
        compose_required=bool(missing) or not composition_cache_hit,
    )


class WorkflowArtifactPublisher(Protocol):
    def publish(
        self,
        workflow: VideoWorkflowVersion,
        manifest: CompositionManifest,
        composition: CompositionResult,
    ) -> UUID: ...


class WorkflowComposer:
    def __init__(self, publisher: WorkflowArtifactPublisher, *, composer_version: str) -> None:
        self._publisher = publisher
        self._composer_version = composer_version

    def compose(
        self,
        workflow: VideoWorkflowVersion,
        *,
        profile: RenderProfile,
        clips: tuple[WorkflowClipEvidence, ...],
        output: Path,
        staging_root: Path,
    ) -> WorkflowCompositionResult:
        expected_scene_ids = tuple(
            node.scene_block_version_id
            for node in workflow.nodes
            if node.kind is WorkflowNodeKind.SCENE
        )
        actual_scene_ids = tuple(clip.scene_block_version_id for clip in clips)
        if actual_scene_ids != expected_scene_ids:
            return WorkflowCompositionResult(
                succeeded=False, failure_code="composition_input_not_ready"
            )
        if any(
            not clip.succeeded
            or clip.owner_id != workflow.owner_id
            or clip.project_id != workflow.project_id
            or clip.profile is not profile
            or clip.byte_size <= 0
            for clip in clips
        ):
            return WorkflowCompositionResult(
                succeeded=False, failure_code="composition_input_not_ready"
            )
        composition: CompositionResult | None = None
        try:
            media = tuple(
                inspect_clip(ClipInput(clip.path, clip.profile, clip.artifact_sha256))
                for clip in clips
            )
            if any(
                item.byte_size != clip.byte_size
                for item, clip in zip(media, clips, strict=True)
            ):
                return WorkflowCompositionResult(
                    succeeded=False, failure_code="composition_artifact_size_mismatch"
                )
            manifest = build_composition_manifest(
                workflow,
                profile=profile,
                clips=tuple(
                    SceneClipDescriptor(
                        scene_block_version_id=clip.scene_block_version_id,
                        artifact_sha256=clip.artifact_sha256,
                        duration_seconds=descriptor.duration_seconds,
                    )
                    for clip, descriptor in zip(clips, media, strict=True)
                ),
                composer_version=self._composer_version,
            )
            composition = compose_mp4s(
                tuple(
                    ClipInput(clip.path, clip.profile, clip.artifact_sha256)
                    for clip in clips
                ),
                output,
                staging_root=staging_root,
            )
            artifact_id = self._publisher.publish(workflow, manifest, composition)
        except ConcatError:
            return WorkflowCompositionResult(
                succeeded=False, failure_code="composition_media_invalid"
            )
        except (OSError, ValueError, WorkflowValidationError):
            if composition is not None and not composition.reused_single_clip:
                composition.path.unlink(missing_ok=True)
            return WorkflowCompositionResult(
                succeeded=False, failure_code="composition_publish_failed"
            )
        return WorkflowCompositionResult(
            succeeded=True,
            manifest=manifest,
            artifact_id=artifact_id,
            media_sha256=composition.media.sha256,
        )


def build_composition_manifest(
    workflow: VideoWorkflowVersion,
    *,
    profile: RenderProfile,
    clips: tuple[SceneClipDescriptor, ...],
    composer_version: str,
) -> CompositionManifest:
    expected = tuple(
        node.scene_block_version_id
        for node in workflow.nodes
        if node.kind is WorkflowNodeKind.SCENE
    )
    actual = tuple(clip.scene_block_version_id for clip in clips)
    if actual != expected:
        raise WorkflowValidationError(
            "composition_scene_order_mismatch",
            "Composition clips must exactly match workflow scene order.",
        )
    return CompositionManifest(
        workflow_version_id=workflow.id,
        profile=profile,
        clips=tuple(
            CompositionManifestClip(
                scene_block_version_id=clip.scene_block_version_id,
                artifact_sha256=clip.artifact_sha256,
                duration_seconds=clip.duration_seconds,
                position=index,
            )
            for index, clip in enumerate(clips, start=1)
        ),
        total_duration_seconds=sum(clip.duration_seconds for clip in clips),
        composer_version=composer_version,
    )


def composition_cache_key(
    workflow: VideoWorkflowVersion,
    manifest: CompositionManifest,
) -> str:
    if manifest.workflow_version_id != workflow.id:
        raise WorkflowValidationError(
            "composition_workflow_version_mismatch",
            "Manifest must identify the supplied WorkflowVersion.",
        )
    node_positions = {node.id: index for index, node in enumerate(workflow.nodes)}
    payload = {
        "schema": "composition-cache-v1",
        "global_brief": workflow.global_brief,
        "graph": {
            "nodes": [
                {
                    "kind": node.kind,
                    "scene_block_version_id": node.scene_block_version_id,
                }
                for node in workflow.nodes
            ],
            "edges": [
                (node_positions[edge.source_node_id], node_positions[edge.target_node_id])
                for edge in workflow.edges
            ],
        },
        "profile": manifest.profile,
        "clips": [
            {
                "scene_block_version_id": clip.scene_block_version_id,
                "artifact_sha256": clip.artifact_sha256,
                "duration_seconds": clip.duration_seconds,
                "position": clip.position,
            }
            for clip in manifest.clips
        ],
        "composer_version": manifest.composer_version,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
