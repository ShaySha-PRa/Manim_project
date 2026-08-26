from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from manim_workbench_contracts import (
    CompositionManifest,
    CompositionManifestClip,
    GlobalBrief,
    Language,
    RenderJobLease,
    RenderJobSubmission,
    RenderProfile,
    SceneBlockVersion,
    ScenePipelineMode,
    VideoWorkflowVersion,
    WorkflowArtifact,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowStylePreset,
)
from pydantic import ValidationError


def test_render_job_contracts_require_exactly_one_typed_source() -> None:
    submission = {
        "project_id": uuid4(),
        "owner_id": uuid4(),
        "profile": RenderProfile.PREVIEW,
        "idempotency_key": "typed-source-contract-key",
    }
    with pytest.raises(ValidationError, match="exactly one"):
        RenderJobSubmission(**submission)
    with pytest.raises(ValidationError, match="exactly one"):
        RenderJobSubmission(
            **submission,
            code_version_id=uuid4(),
            program_render_segment_id=uuid4(),
        )
    with pytest.raises(ValidationError, match="segment identity"):
        RenderJobSubmission(
            **submission,
            program_render_segment_id=uuid4(),
        )
    scientific_submission = RenderJobSubmission(
        **submission,
        program_render_segment_id=uuid4(),
        concat_group_id=uuid4(),
        segment_index=0,
    )
    assert scientific_submission.segment_index == 0

    lease = {
        "job_id": uuid4(),
        "target_duration_seconds": 30,
        "profile": RenderProfile.PREVIEW,
        "scene_class": "GeneratedScene",
        "source_code": "class GeneratedScene: pass",
        "source_sha256": "a" * 64,
        "lease_token": "b" * 64,
        "lease_expires_at": datetime.now(timezone.utc),
        "attempt_number": 1,
    }
    with pytest.raises(ValidationError, match="exactly one"):
        RenderJobLease(**lease)
    with pytest.raises(ValidationError, match="content_plan_version_id"):
        RenderJobLease(**lease, code_version_id=uuid4())
    scientific = RenderJobLease(**lease, program_render_segment_id=uuid4())
    assert scientific.content_plan_version_id is None


def _brief(**updates) -> GlobalBrief:  # type: ignore[no-untyped-def]
    values = {
        "title": "Lorenz system",
        "language": Language.ZH_CN,
        "target_duration_seconds": 120,
        "aspect_ratio": "16:9",
        "style_preset": WorkflowStylePreset.DARK_SCIENTIFIC,
        "background": "#10131a",
        "palette": ("#4c8dff", "#ffd84c", "#ff5c5c"),
        "notation": {"sigma": "σ"},
        "scientific_parameters": {"sigma": 10.0, "rho": 28.0},
    }
    return GlobalBrief(**{**values, **updates})


def _workflow() -> VideoWorkflowVersion:
    first_id = uuid4()
    second_id = uuid4()
    compose_id = uuid4()
    export_id = uuid4()
    return VideoWorkflowVersion(
        id=uuid4(),
        workflow_id=uuid4(),
        project_id=uuid4(),
        owner_id=uuid4(),
        version=1,
        parent_version_id=None,
        global_brief=_brief(),
        nodes=(
            WorkflowNode(
                id=first_id,
                kind=WorkflowNodeKind.SCENE,
                scene_block_version_id=uuid4(),
            ),
            WorkflowNode(
                id=second_id,
                kind=WorkflowNodeKind.SCENE,
                scene_block_version_id=uuid4(),
            ),
            WorkflowNode(id=compose_id, kind=WorkflowNodeKind.COMPOSE),
            WorkflowNode(id=export_id, kind=WorkflowNodeKind.EXPORT),
        ),
        edges=(
            WorkflowEdge(source_node_id=first_id, target_node_id=second_id),
            WorkflowEdge(source_node_id=second_id, target_node_id=compose_id),
            WorkflowEdge(source_node_id=compose_id, target_node_id=export_id),
        ),
        created_at=datetime.now(timezone.utc),
    )


def test_workflow_contracts_are_strict_frozen_and_round_trip() -> None:
    workflow = _workflow()
    restored = VideoWorkflowVersion.model_validate_json(workflow.model_dump_json())
    assert restored == workflow
    with pytest.raises(ValidationError, match="frozen"):
        workflow.version = 2  # type: ignore[misc]
    with pytest.raises(ValidationError, match="extra"):
        GlobalBrief.model_validate({**_brief().model_dump(), "unbounded": True})


def test_workflow_artifact_requires_exactly_one_real_run_source() -> None:
    values = {
        "id": uuid4(),
        "project_id": uuid4(),
        "owner_id": uuid4(),
        "profile": RenderProfile.PREVIEW,
        "relative_path": "workflow/scene.mp4",
        "sha256": "a" * 64,
        "byte_size": 1024,
        "duration_seconds": 30.0,
        "created_at": datetime.now(timezone.utc),
    }
    artifact = WorkflowArtifact(**values, scene_block_run_id=uuid4())
    assert artifact.media_type == "video/mp4"
    with pytest.raises(ValidationError, match="exactly one"):
        WorkflowArtifact(**values)
    with pytest.raises(ValidationError, match="exactly one"):
        WorkflowArtifact(
            **values,
            scene_block_run_id=uuid4(),
            composition_run_id=uuid4(),
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"aspect_ratio": "4:3"},
        {"style_preset": "unknown"},
        {"target_duration_seconds": 601},
        {"scientific_parameters": {"rho": float("inf")}},
    ],
)
def test_global_brief_rejects_unsupported_or_unbounded_values(updates) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError):
        _brief(**updates)


@pytest.mark.parametrize("duration", [14, 121])
def test_scene_block_duration_and_parent_chain_are_bounded(duration: int) -> None:
    with pytest.raises(ValidationError):
        SceneBlockVersion(
            id=uuid4(),
            project_id=uuid4(),
            workflow_id=uuid4(),
            owner_id=uuid4(),
            version=2,
            parent_version_id=None,
            title="Scene",
            prompt="Explain the scene",
            pipeline_mode=ScenePipelineMode.AUTO,
            target_duration_seconds=duration,
            created_at=datetime.now(timezone.utc),
        )


def test_workflow_requires_two_to_eight_scenes_and_one_compose_export() -> None:
    workflow = _workflow()
    with pytest.raises(ValidationError):
        VideoWorkflowVersion.model_validate(
            {
                **workflow.model_dump(),
                "nodes": tuple(
                    node
                    for node in workflow.nodes
                    if node.kind is not WorkflowNodeKind.SCENE
                    or node == workflow.nodes[0]
                ),
            }
        )


def test_manifest_requires_ordered_clips_and_matching_bounded_total() -> None:
    clips = (
        CompositionManifestClip(
            scene_block_version_id=uuid4(),
            artifact_sha256="a" * 64,
            duration_seconds=30,
            position=1,
        ),
        CompositionManifestClip(
            scene_block_version_id=uuid4(),
            artifact_sha256="b" * 64,
            duration_seconds=45,
            position=2,
        ),
    )
    manifest = CompositionManifest(
        workflow_version_id=uuid4(),
        profile=RenderProfile.PREVIEW,
        clips=clips,
        total_duration_seconds=75,
        composer_version="workflow-mvp-v1",
    )
    assert CompositionManifest.model_validate_json(manifest.model_dump_json()) == manifest
    with pytest.raises(ValidationError, match="positions"):
        CompositionManifest(
            workflow_version_id=uuid4(),
            profile=RenderProfile.PREVIEW,
            clips=(clips[1], clips[0]),
            total_duration_seconds=75,
            composer_version="workflow-mvp-v1",
        )
