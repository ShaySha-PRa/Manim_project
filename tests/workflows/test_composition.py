from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import av
import pytest
from manim_workbench_api.workflows import (
    SceneClipDescriptor,
    WorkflowClipEvidence,
    WorkflowComposer,
    WorkflowExecutionPlan,
    WorkflowValidationError,
    build_composition_manifest,
    composition_cache_key,
    plan_workflow_execution,
)
from manim_workbench_contracts import (
    GlobalBrief,
    Language,
    RenderProfile,
    VideoWorkflowVersion,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowStylePreset,
)

OWNER = UUID("00000000-0000-0000-0000-000000000001")
PROJECT = UUID("10000000-0000-0000-0000-000000000001")
WORKFLOW = UUID("20000000-0000-0000-0000-000000000001")


def _workflow(scene_ids: tuple[UUID, ...]) -> VideoWorkflowVersion:
    nodes = tuple(
        WorkflowNode(id=uuid4(), kind=WorkflowNodeKind.SCENE, scene_block_version_id=item)
        for item in scene_ids
    ) + (
        WorkflowNode(id=uuid4(), kind=WorkflowNodeKind.COMPOSE),
        WorkflowNode(id=uuid4(), kind=WorkflowNodeKind.EXPORT),
    )
    return VideoWorkflowVersion(
        id=uuid4(),
        workflow_id=WORKFLOW,
        project_id=PROJECT,
        owner_id=OWNER,
        version=1,
        parent_version_id=None,
        global_brief=GlobalBrief(
            title="Workflow",
            language=Language.EN_US,
            target_duration_seconds=120,
            style_preset=WorkflowStylePreset.PRESENTATION,
            background="#111111",
            palette=("#ffffff",),
        ),
        nodes=nodes,
        edges=tuple(
            WorkflowEdge(source_node_id=nodes[index].id, target_node_id=nodes[index + 1].id)
            for index in range(len(nodes) - 1)
        ),
        created_at=datetime.now(timezone.utc),
    )


def _clips(scene_ids: tuple[UUID, ...]) -> tuple[SceneClipDescriptor, ...]:
    return tuple(
        SceneClipDescriptor(
            scene_block_version_id=item,
            intent_ref=item,
            animation_ir_ref=UUID(int=item.int ^ 1),
            compiled_program_ref=UUID(int=item.int ^ 2),
            artifact_sha256=f"{index + 1:x}" * 64,
            duration_seconds=30.0,
        )
        for index, item in enumerate(scene_ids)
    )


def _write_clip(
    path: Path,
    frames: int = 6,
    *,
    rate: int = 15,
    width: int = 160,
    pixel_format: str = "yuv420p",
) -> None:
    output = av.open(str(path), mode="w")
    stream = output.add_stream("h264", rate=rate)
    stream.width = width
    stream.height = 90
    stream.pix_fmt = pixel_format
    for _ in range(frames):
        frame = av.VideoFrame(width=width, height=90, format=pixel_format)
        for plane in frame.planes:
            plane.update(bytes(plane.buffer_size))
        packet = stream.encode(frame)
        if packet:
            output.mux(packet)
    packet = stream.encode(None)
    if packet:
        output.mux(packet)
    output.close()


class Publisher:
    def __init__(self) -> None:
        self.artifact_id = uuid4()
        self.calls = []

    def publish(self, workflow, manifest, composition):  # type: ignore[no-untyped-def]
        self.calls.append((workflow, manifest, composition))
        return self.artifact_id


def test_manifest_and_cache_key_are_stable_and_complete() -> None:
    scene_ids = (uuid4(), uuid4(), uuid4())
    workflow = _workflow(scene_ids)
    manifest = build_composition_manifest(
        workflow,
        profile=RenderProfile.PREVIEW,
        clips=_clips(scene_ids),
        composer_version="workflow-mvp-v1",
    )
    assert tuple(clip.position for clip in manifest.clips) == (1, 2, 3)
    assert tuple(clip.intent_ref for clip in manifest.clips) == scene_ids
    assert all(clip.animation_ir_ref is not None for clip in manifest.clips)
    assert all(clip.compiled_program_ref is not None for clip in manifest.clips)
    assert manifest.total_duration_seconds == 90
    assert composition_cache_key(workflow, manifest) == composition_cache_key(
        workflow, manifest
    )


def test_reorder_profile_clip_hash_or_composer_changes_composition_key() -> None:
    scene_ids = (uuid4(), uuid4(), uuid4())
    workflow = _workflow(scene_ids)
    manifest = build_composition_manifest(
        workflow,
        profile=RenderProfile.PREVIEW,
        clips=_clips(scene_ids),
        composer_version="workflow-mvp-v1",
    )
    baseline = composition_cache_key(workflow, manifest)

    reordered_ids = (scene_ids[1], scene_ids[0], scene_ids[2])
    reordered_workflow = _workflow(reordered_ids)
    reordered = build_composition_manifest(
        reordered_workflow,
        profile=RenderProfile.PREVIEW,
        clips=_clips(reordered_ids),
        composer_version="workflow-mvp-v1",
    )
    assert composition_cache_key(reordered_workflow, reordered) != baseline
    assert composition_cache_key(
        workflow, manifest.model_copy(update={"profile": RenderProfile.FINAL})
    ) != baseline
    changed_hash = manifest.model_copy(
        update={
            "clips": (
                manifest.clips[0].model_copy(update={"artifact_sha256": "f" * 64}),
                *manifest.clips[1:],
            )
        }
    )
    assert composition_cache_key(workflow, changed_hash) != baseline
    assert composition_cache_key(
        workflow, manifest.model_copy(update={"composer_version": "workflow-mvp-v2"})
    ) != baseline


def test_manifest_rejects_missing_or_wrong_order_scene_clip() -> None:
    scene_ids = (uuid4(), uuid4())
    workflow = _workflow(scene_ids)
    with pytest.raises(WorkflowValidationError) as caught:
        build_composition_manifest(
            workflow,
            profile=RenderProfile.FINAL,
            clips=tuple(reversed(_clips(scene_ids))),
            composer_version="workflow-mvp-v1",
        )
    assert caught.value.code == "composition_scene_order_mismatch"


def test_execution_plan_distinguishes_reorder_local_change_and_complete_cache_hit() -> None:
    assert plan_workflow_execution(
        (True, True, True, True), composition_cache_hit=False
    ) == WorkflowExecutionPlan(scene_indexes_to_run=(), compose_required=True)
    assert plan_workflow_execution(
        (True, True, False, True), composition_cache_hit=False
    ) == WorkflowExecutionPlan(scene_indexes_to_run=(2,), compose_required=True)
    assert plan_workflow_execution(
        (True, True, True, True), composition_cache_hit=True
    ) == WorkflowExecutionPlan(scene_indexes_to_run=(), compose_required=False)


def test_workflow_composer_hard_cuts_three_verified_clips_and_publishes_atomically(
    tmp_path: Path,
) -> None:
    scene_ids = (uuid4(), uuid4(), uuid4())
    workflow = _workflow(scene_ids)
    evidence = []
    for index, scene_id in enumerate(scene_ids):
        path = tmp_path / f"scene-{index}.mp4"
        _write_clip(path, frames=6 + index)
        digest = sha256(path.read_bytes()).hexdigest()
        evidence.append(
            WorkflowClipEvidence(
                scene_block_version_id=scene_id,
                artifact_id=uuid4(),
                owner_id=OWNER,
                project_id=PROJECT,
                profile=RenderProfile.PREVIEW,
                path=path,
                artifact_sha256=digest,
                byte_size=path.stat().st_size,
            )
        )
    publisher = Publisher()
    result = WorkflowComposer(publisher, composer_version="workflow-mvp-v1").compose(
        workflow,
        profile=RenderProfile.PREVIEW,
        clips=tuple(evidence),
        output=tmp_path / "workflow.mp4",
        staging_root=tmp_path,
    )
    assert result.succeeded
    assert result.artifact_id == publisher.artifact_id
    assert result.manifest is not None
    assert tuple(clip.scene_block_version_id for clip in result.manifest.clips) == scene_ids
    assert result.manifest.total_duration_seconds == pytest.approx(21 / 15)
    assert len(publisher.calls) == 1
    with av.open(str(tmp_path / "workflow.mp4")) as container:
        assert len(list(container.decode(video=0))) >= 19


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("missing", "composition_input_not_ready"),
        ("failed", "composition_input_not_ready"),
        ("profile", "composition_input_not_ready"),
        ("hash", "composition_media_invalid"),
        ("zero", "composition_media_invalid"),
        ("fps", "composition_media_invalid"),
        ("dimensions", "composition_media_invalid"),
        ("pixel_format", "composition_media_invalid"),
    ],
)
def test_composer_rejects_unready_or_incompatible_inputs_without_publishing(
    tmp_path: Path, failure: str, expected: str
) -> None:
    scene_ids = (uuid4(), uuid4())
    workflow = _workflow(scene_ids)
    evidence = []
    for index, scene_id in enumerate(scene_ids):
        path = tmp_path / f"{failure}-{index}.mp4"
        if failure == "zero" and index == 1:
            path.write_bytes(b"not-a-decodable-mp4")
        else:
            _write_clip(
                path,
                rate=24 if failure == "fps" and index == 1 else 15,
                width=192 if failure == "dimensions" and index == 1 else 160,
                pixel_format=(
                    "yuv444p" if failure == "pixel_format" and index == 1 else "yuv420p"
                ),
            )
        payload = path.read_bytes()
        evidence.append(
            WorkflowClipEvidence(
                scene_block_version_id=scene_id,
                artifact_id=uuid4(),
                owner_id=OWNER,
                project_id=PROJECT,
                profile=(
                    RenderProfile.FINAL
                    if failure == "profile" and index == 1
                    else RenderProfile.PREVIEW
                ),
                path=path,
                artifact_sha256=(
                    "0" * 64 if failure == "hash" and index == 1 else sha256(payload).hexdigest()
                ),
                byte_size=len(payload),
                succeeded=not (failure == "failed" and index == 1),
            )
        )
    if failure == "missing":
        evidence.pop()
    publisher = Publisher()
    output = tmp_path / f"{failure}-output.mp4"
    result = WorkflowComposer(publisher, composer_version="workflow-mvp-v1").compose(
        workflow,
        profile=RenderProfile.PREVIEW,
        clips=tuple(evidence),
        output=output,
        staging_root=tmp_path,
    )
    assert not result.succeeded
    assert result.failure_code == expected
    assert publisher.calls == []
    assert not output.exists()
