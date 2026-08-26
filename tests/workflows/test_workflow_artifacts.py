from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from manim_workbench_api.auth.models import SessionPrincipal
from manim_workbench_api.delivery.service import DeliveryNotFound, DeliveryService
from manim_workbench_api.workflows import (
    ProgramRenderConflict,
    ProgramRenderSource,
    ProgramRenderStore,
    WorkflowArtifactConflict,
    WorkflowArtifactStore,
)
from manim_workbench_api.workflows.repository import WorkflowRepository
from manim_workbench_contracts import RenderProfile
from sqlalchemy import Engine

from tests.workflows.test_repository import OWNER_A, OWNER_B, PROJECT_A, _workflow_fixture

pytest_plugins = ("tests.workflows.test_repository",)


def _principal(owner_id):  # type: ignore[no-untyped-def]
    now = datetime.now(timezone.utc)
    return SessionPrincipal(
        user_id=owner_id,
        email="owner@test.dev",
        created_at=now,
        must_change_password=False,
        session_id=uuid4(),
        expires_at=now + timedelta(hours=1),
    )


def _scene_run(engine: Engine):  # type: ignore[no-untyped-def]
    repository = WorkflowRepository(engine)
    _, first, _, workflow = _workflow_fixture(repository)
    return repository.create_scene_block_run(
        scene_block_version_id=first.id,
        workflow_version_id=workflow.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        cache_key="a" * 64,
        idempotency_key="workflow-artifact-scene-run",
    )


def test_workflow_artifact_is_atomic_idempotent_and_owner_deliverable(
    engine: Engine, tmp_path: Path
) -> None:
    run = _scene_run(engine)
    artifact_root = tmp_path / "artifacts"
    staging_root = tmp_path / "staging"
    store = WorkflowArtifactStore(engine, artifact_root, staging_root)
    source = staging_root / "scene.mp4"
    source.write_bytes(b"real-composed-video-evidence")
    artifact = store.publish(
        source,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        profile=RenderProfile.PREVIEW,
        duration_seconds=30.0,
        scene_block_run_id=run.id,
    )
    assert not source.exists()
    opened = DeliveryService(engine, artifact_root).artifact(
        _principal(OWNER_A), artifact.id, attachment=False
    )
    assert opened.path.read_bytes() == b"real-composed-video-evidence"
    retry = staging_root / "retry.mp4"
    retry.write_bytes(b"real-composed-video-evidence")
    assert store.publish(
        retry,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        profile=RenderProfile.PREVIEW,
        duration_seconds=30.0,
        scene_block_run_id=run.id,
    ).id == artifact.id
    with pytest.raises(DeliveryNotFound):
        DeliveryService(engine, artifact_root).artifact(
            _principal(OWNER_B), artifact.id, attachment=False
        )


def test_workflow_artifact_rejects_symlink_cross_owner_and_conflicting_retry(
    engine: Engine, tmp_path: Path
) -> None:
    run = _scene_run(engine)
    artifact_root = tmp_path / "artifacts"
    staging_root = tmp_path / "staging"
    store = WorkflowArtifactStore(engine, artifact_root, staging_root)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    linked = staging_root / "linked.mp4"
    linked.symlink_to(outside)
    with pytest.raises(ValueError, match="regular staging"):
        store.publish(
            linked,
            project_id=PROJECT_A,
            owner_id=OWNER_A,
            profile=RenderProfile.PREVIEW,
            duration_seconds=30.0,
            scene_block_run_id=run.id,
        )
    first = staging_root / "first.mp4"
    first.write_bytes(b"first")
    store.publish(
        first,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        profile=RenderProfile.PREVIEW,
        duration_seconds=30.0,
        scene_block_run_id=run.id,
    )
    conflict = staging_root / "conflict.mp4"
    conflict.write_bytes(b"different")
    with pytest.raises(WorkflowArtifactConflict):
        store.publish(
            conflict,
            project_id=PROJECT_A,
            owner_id=OWNER_A,
            profile=RenderProfile.PREVIEW,
            duration_seconds=30.0,
            scene_block_run_id=run.id,
        )


def test_program_render_store_is_owner_scoped_contiguous_and_idempotent(engine: Engine) -> None:
    scene_run = _scene_run(engine)
    store = ProgramRenderStore(engine)
    source_codes = tuple(
        f"from manim import Scene\nclass Scene{index}(Scene):\n    pass\n"
        for index in range(3)
    )
    sources = tuple(
        ProgramRenderSource(
            source_code=source,
            source_sha256=sha256(source.encode()).hexdigest(),
            scene_class=f"Scene{index}",
            target_duration_seconds=30,
        )
        for index, source in enumerate(source_codes)
    )
    hashes = tuple(source.source_sha256 for source in sources)
    run, segments = store.create_or_get(
        scene_block_run_id=scene_run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        profile=RenderProfile.FINAL,
        program_sha256="f" * 64,
        quality_policy="teaching",
        segment_sources=sources,
    )
    assert tuple(segment.segment_index for segment in segments) == (0, 1, 2)
    assert tuple(segment.source_sha256 for segment in segments) == hashes
    assert store.create_or_get(
        scene_block_run_id=scene_run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        profile=RenderProfile.FINAL,
        program_sha256="f" * 64,
        quality_policy="teaching",
        segment_sources=sources,
    )[0].id == run.id
    assert store.find(scene_run.id, PROJECT_A, OWNER_B, RenderProfile.FINAL) is None
    with pytest.raises(ProgramRenderConflict):
        store.create_or_get(
            scene_block_run_id=scene_run.id,
            project_id=PROJECT_A,
            owner_id=OWNER_A,
            profile=RenderProfile.FINAL,
            program_sha256="e" * 64,
            quality_policy="teaching",
            segment_sources=sources,
        )
