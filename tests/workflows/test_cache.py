from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from manim_workbench_api.workflows import (
    CacheArtifactDescriptor,
    CacheValidationError,
    SceneCacheService,
    SceneCacheVersions,
    scene_cache_key,
    verify_cache_artifact,
)
from manim_workbench_contracts import (
    GlobalBrief,
    Language,
    RenderProfile,
    SceneBlockVersion,
    ScenePipeline,
    ScenePipelineMode,
    WorkflowStylePreset,
)

OWNER = UUID("00000000-0000-0000-0000-000000000001")
PROJECT = UUID("10000000-0000-0000-0000-000000000001")
WORKFLOW = UUID("20000000-0000-0000-0000-000000000001")
VERSIONS = SceneCacheVersions(
    pipeline="scientific-v2",
    template="intent-v1",
    tool="tools-v2",
    compiler="manim-ir-v2",
    renderer="manimce-0.21.0",
)


def _block(prompt: str = "Render Lorenz trajectories") -> SceneBlockVersion:
    return SceneBlockVersion(
        id=uuid4(),
        workflow_id=WORKFLOW,
        project_id=PROJECT,
        owner_id=OWNER,
        version=1,
        parent_version_id=None,
        title="Lorenz",
        prompt=prompt,
        pipeline_mode=ScenePipelineMode.SCIENTIFIC,
        target_duration_seconds=30,
        created_at=datetime.now(timezone.utc),
    )


def _brief(background: str = "#111111") -> GlobalBrief:
    return GlobalBrief(
        title="Dynamics",
        language=Language.EN_US,
        target_duration_seconds=120,
        style_preset=WorkflowStylePreset.DARK_SCIENTIFIC,
        background=background,
        palette=("#4488ff", "#ffcc22"),
    )


def _key(**updates):  # type: ignore[no-untyped-def]
    values = {
        "block": _block(),
        "global_brief": _brief(),
        "asset_hashes": ("a" * 64, "b" * 64),
        "pipeline": ScenePipeline.SCIENTIFIC,
        "versions": VERSIONS,
        "profile": RenderProfile.PREVIEW,
        "previous_scene_summary": "equations introduced",
    }
    values.update(updates)
    return scene_cache_key(**values)


def test_scene_cache_is_canonical_and_ignores_version_identity_and_time() -> None:
    first = _block()
    same_content_new_identity = first.model_copy(
        update={
            "id": uuid4(),
            "version": 2,
            "parent_version_id": first.id,
            "created_at": datetime.now(timezone.utc),
        }
    )
    assert _key(block=first) == _key(block=same_content_new_identity)
    assert len(_key()) == 64


def test_every_semantic_scene_input_invalidates_cache_key() -> None:
    baseline = _key()
    assert _key(block=_block("Different prompt")) != baseline
    assert _key(global_brief=_brief("#222222")) != baseline
    assert _key(asset_hashes=("b" * 64, "a" * 64)) != baseline
    assert _key(profile=RenderProfile.FINAL) != baseline
    assert _key(
        versions=SceneCacheVersions(
            pipeline="scientific-v3",
            template=VERSIONS.template,
            tool=VERSIONS.tool,
            compiler=VERSIONS.compiler,
            renderer=VERSIONS.renderer,
        )
    ) != baseline
    assert _key(previous_scene_summary="different context") != baseline


def test_cache_hit_revalidates_boundary_size_hash_path_and_media(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    payload = b"fake-mp4-for-boundary-test"
    path = root / "clip.mp4"
    path.write_bytes(payload)
    descriptor = CacheArtifactDescriptor(
        owner_id=OWNER,
        project_id=PROJECT,
        profile=RenderProfile.PREVIEW,
        relative_path="clip.mp4",
        sha256=hashlib.sha256(payload).hexdigest(),
        byte_size=len(payload),
    )
    assert verify_cache_artifact(
        descriptor,
        artifact_root=root,
        owner_id=OWNER,
        project_id=PROJECT,
        profile=RenderProfile.PREVIEW,
        media_probe=lambda candidate: candidate == path,
    ) == path

    invalid = (
        replace(descriptor, owner_id=uuid4()),
        replace(descriptor, byte_size=len(payload) + 1),
        replace(descriptor, sha256="0" * 64),
        replace(descriptor, relative_path="../outside.mp4"),
    )
    for candidate in invalid:
        with pytest.raises(CacheValidationError):
            verify_cache_artifact(
                candidate,
                artifact_root=root,
                owner_id=OWNER,
                project_id=PROJECT,
                profile=RenderProfile.PREVIEW,
                media_probe=lambda _path: True,
            )
    with pytest.raises(CacheValidationError, match="media_invalid"):
        verify_cache_artifact(
            descriptor,
            artifact_root=root,
            owner_id=OWNER,
            project_id=PROJECT,
            profile=RenderProfile.PREVIEW,
            media_probe=lambda _path: False,
        )


class DictLookup:
    def __init__(self, values):  # type: ignore[no-untyped-def]
        self.values = values

    def find_scene_cache_artifact(
        self, key, _project_id, _owner_id, _profile  # type: ignore[no-untyped-def]
    ):
        return self.values.get(key)


def test_local_prompt_change_reuses_other_scenes_and_invalid_cache_is_a_miss(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    descriptors = {}
    keys = tuple(hashlib.sha256(f"scene-{index}".encode()).hexdigest() for index in range(4))
    for index, key in enumerate(keys):
        payload = f"clip-{index}".encode()
        (root / f"{index}.mp4").write_bytes(payload)
        descriptors[key] = CacheArtifactDescriptor(
            owner_id=OWNER,
            project_id=PROJECT,
            profile=RenderProfile.PREVIEW,
            relative_path=f"{index}.mp4",
            sha256=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
        )
    changed_key = hashlib.sha256(b"scene-2-new-prompt").hexdigest()
    requested = (keys[0], keys[1], changed_key, keys[3])
    service = SceneCacheService(
        DictLookup(descriptors), artifact_root=root, media_probe=lambda _path: True
    )
    hits = service.lookup_many(
        requested,
        owner_id=OWNER,
        project_id=PROJECT,
        profile=RenderProfile.PREVIEW,
    )
    assert tuple(hit is not None for hit in hits) == (True, True, False, True)

    descriptors[keys[0]] = replace(descriptors[keys[0]], sha256="0" * 64)
    assert service.lookup(
        keys[0], owner_id=OWNER, project_id=PROJECT, profile=RenderProfile.PREVIEW
    ) is None
