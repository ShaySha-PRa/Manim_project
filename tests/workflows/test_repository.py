from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from manim_workbench_api.database import create_database_engine
from manim_workbench_api.workflows import (
    WORKFLOW_NOT_FOUND,
    WORKFLOW_REFERENCE_INVALID,
    WORKFLOW_VERSION_CONFLICT,
    WorkflowRepository,
)
from manim_workbench_contracts import (
    CompositionRunStatus,
    GlobalBrief,
    Language,
    RenderProfile,
    SceneBlockRunStatus,
    ScenePipelineMode,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowStylePreset,
)
from sqlalchemy import Engine, text

from tests.workflows.migration_support import upgrade_workflow_database

OWNER_A = UUID("00000000-0000-0000-0000-000000000001")
OWNER_B = UUID("00000000-0000-0000-0000-000000000002")
PROJECT_A = UUID("10000000-0000-0000-0000-000000000001")
PROJECT_B = UUID("10000000-0000-0000-0000-000000000002")
PROJECT_ARCHIVED = UUID("10000000-0000-0000-0000-000000000003")


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    path = tmp_path / "repository.db"
    upgrade_workflow_database(path)
    result = create_database_engine(f"sqlite:///{path}")
    now = "2026-08-23T00:00:00+00:00"
    with result.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id,email,created_at) VALUES (:id,:email,:now)"),
            [
                {"id": str(OWNER_A), "email": "a@test.dev", "now": now},
                {"id": str(OWNER_B), "email": "b@test.dev", "now": now},
            ],
        )
        connection.execute(
            text(
                "INSERT INTO projects (id,owner_id,title,created_at,archived_at) "
                "VALUES (:id,:owner_id,:title,:now,:archived_at)"
            ),
            [
                {
                    "id": str(PROJECT_A),
                    "owner_id": str(OWNER_A),
                    "title": "A",
                    "now": now,
                    "archived_at": None,
                },
                {
                    "id": str(PROJECT_B),
                    "owner_id": str(OWNER_B),
                    "title": "B",
                    "now": now,
                    "archived_at": None,
                },
                {
                    "id": str(PROJECT_ARCHIVED),
                    "owner_id": str(OWNER_A),
                    "title": "Archived",
                    "now": now,
                    "archived_at": now,
                },
            ],
        )
    return result


def _brief() -> GlobalBrief:
    return GlobalBrief(
        title="Lorenz workflow",
        language=Language.ZH_CN,
        target_duration_seconds=120,
        style_preset=WorkflowStylePreset.DARK_SCIENTIFIC,
        background="#101018",
        palette=("#4488ff", "#ffcc22"),
    )


def _linear_nodes(
    first: UUID, second: UUID
) -> tuple[tuple[WorkflowNode, ...], tuple[WorkflowEdge, ...]]:
    ids = tuple(uuid4() for _ in range(4))
    nodes = (
        WorkflowNode(id=ids[0], kind=WorkflowNodeKind.SCENE, scene_block_version_id=first),
        WorkflowNode(id=ids[1], kind=WorkflowNodeKind.SCENE, scene_block_version_id=second),
        WorkflowNode(id=ids[2], kind=WorkflowNodeKind.COMPOSE),
        WorkflowNode(id=ids[3], kind=WorkflowNodeKind.EXPORT),
    )
    edges = tuple(
        WorkflowEdge(source_node_id=ids[index], target_node_id=ids[index + 1])
        for index in range(3)
    )
    return nodes, edges


def _workflow_fixture(repository: WorkflowRepository) -> tuple[UUID, object, object, object]:
    workflow_id = repository.create_workflow(PROJECT_A, OWNER_A)
    first = repository.create_scene_block(
        workflow_id=workflow_id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        title="Intro",
        prompt="Explain the Lorenz equations.",
        pipeline_mode=ScenePipelineMode.TEACHING,
        target_duration_seconds=30,
    )
    second = repository.create_scene_block(
        workflow_id=workflow_id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        title="Trajectory",
        prompt="Render a Lorenz trajectory.",
        pipeline_mode=ScenePipelineMode.SCIENTIFIC,
        target_duration_seconds=45,
    )
    nodes, edges = _linear_nodes(first.id, second.id)
    version = repository.append_workflow_version(
        workflow_id=workflow_id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        global_brief=_brief(),
        nodes=nodes,
        edges=edges,
    )
    return workflow_id, first, second, version


def test_versions_preserve_parent_chain_and_reject_stale_or_forged_parent(engine: Engine) -> None:
    repository = WorkflowRepository(engine)
    workflow_id, first, second, workflow_v1 = _workflow_fixture(repository)
    first_v2 = repository.append_scene_block_version(
        parent_version_id=first.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        title="Intro revised",
        prompt="Explain every Lorenz parameter.",
        pipeline_mode=ScenePipelineMode.TEACHING,
        target_duration_seconds=35,
    )
    assert first_v2.version == 2
    assert first_v2.parent_version_id == first.id
    with pytest.raises(type(WORKFLOW_VERSION_CONFLICT)):
        repository.append_scene_block_version(
            parent_version_id=first.id,
            project_id=PROJECT_A,
            owner_id=OWNER_A,
            title="Stale fork",
            prompt="This parent is no longer current.",
            pipeline_mode=ScenePipelineMode.AUTO,
            target_duration_seconds=30,
        )

    other_workflow, other_first, _, other_v1 = _workflow_fixture(repository)
    nodes, edges = _linear_nodes(first_v2.id, second.id)
    with pytest.raises(type(WORKFLOW_VERSION_CONFLICT)):
        repository.append_workflow_version(
            workflow_id=workflow_id,
            project_id=PROJECT_A,
            owner_id=OWNER_A,
            parent_version_id=other_v1.id,
            global_brief=_brief(),
            nodes=nodes,
            edges=edges,
        )
    assert other_workflow != workflow_id
    assert other_first.workflow_id == other_workflow
    workflow_v2 = repository.append_workflow_version(
        workflow_id=workflow_id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        parent_version_id=workflow_v1.id,
        global_brief=_brief(),
        nodes=nodes,
        edges=edges,
    )
    assert workflow_v2.version == 2
    assert workflow_v2.parent_version_id == workflow_v1.id


def test_owner_project_archive_and_reference_boundaries_are_enforced(engine: Engine) -> None:
    repository = WorkflowRepository(engine)
    workflow_id, first, _, version = _workflow_fixture(repository)
    with pytest.raises(type(WORKFLOW_NOT_FOUND)):
        repository.get_workflow_version(version.id, PROJECT_A, OWNER_B)
    with pytest.raises(type(WORKFLOW_NOT_FOUND)):
        repository.get_scene_block_version(first.id, PROJECT_B, OWNER_B)
    with pytest.raises(type(WORKFLOW_NOT_FOUND)):
        repository.create_workflow(PROJECT_ARCHIVED, OWNER_A)

    foreign_workflow = repository.create_workflow(PROJECT_B, OWNER_B)
    foreign_block = repository.create_scene_block(
        workflow_id=foreign_workflow,
        project_id=PROJECT_B,
        owner_id=OWNER_B,
        title="Foreign",
        prompt="Must not cross the boundary.",
        pipeline_mode=ScenePipelineMode.AUTO,
        target_duration_seconds=30,
    )
    nodes, edges = _linear_nodes(first.id, foreign_block.id)
    with pytest.raises(type(WORKFLOW_REFERENCE_INVALID)):
        repository.append_workflow_version(
            workflow_id=workflow_id,
            project_id=PROJECT_A,
            owner_id=OWNER_A,
            parent_version_id=version.id,
            global_brief=_brief(),
            nodes=nodes,
            edges=edges,
        )

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE projects SET archived_at=:now WHERE id=:id"),
            {"now": "2026-08-23T01:00:00+00:00", "id": str(PROJECT_A)},
        )
    with pytest.raises(type(WORKFLOW_NOT_FOUND)):
        repository.get_workflow_version(version.id, PROJECT_A, OWNER_A)


def test_scene_block_rejects_asset_version_outside_owner_project(engine: Engine) -> None:
    repository = WorkflowRepository(engine)
    workflow_id = repository.create_workflow(PROJECT_A, OWNER_A)
    asset_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO asset_versions "
                "(id,sha256,mime,size_bytes,source,derived_from,columns_json,fields_json,"
                "owner_id,project_id,created_at) VALUES "
                "(:id,:sha,'text/csv',12,'upload',NULL,'[]','{}',:owner,:project,:now)"
            ),
            {
                "id": str(asset_id),
                "sha": "d" * 64,
                "owner": str(OWNER_B),
                "project": str(PROJECT_B),
                "now": "2026-08-23T00:00:00+00:00",
            },
        )
    with pytest.raises(type(WORKFLOW_REFERENCE_INVALID)):
        repository.create_scene_block(
            workflow_id=workflow_id,
            project_id=PROJECT_A,
            owner_id=OWNER_A,
            title="Foreign asset",
            prompt="Visualize the attached CSV.",
            pipeline_mode=ScenePipelineMode.SCIENTIFIC,
            target_duration_seconds=30,
            asset_version_ids=(asset_id,),
        )


def test_scene_run_projection_is_monotonic_and_stale_writer_loses(engine: Engine) -> None:
    repository = WorkflowRepository(engine)
    _, first, _, workflow_version = _workflow_fixture(repository)
    run = repository.create_scene_block_run(
        scene_block_version_id=first.id,
        workflow_version_id=workflow_version.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        cache_key="a" * 64,
        idempotency_key="run-1",
    )
    assert run.status is SceneBlockRunStatus.QUEUED
    assert run.state_version == 0
    planning = repository.append_scene_block_run_event(
        run_id=run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        expected_state_version=0,
        status=SceneBlockRunStatus.PLANNING,
    )
    assert planning.state_version == 1
    with pytest.raises(type(WORKFLOW_VERSION_CONFLICT)):
        repository.append_scene_block_run_event(
            run_id=run.id,
            project_id=PROJECT_A,
            owner_id=OWNER_A,
            expected_state_version=0,
            status=SceneBlockRunStatus.COMPILING,
        )


def test_concurrent_scene_run_state_writers_create_exactly_one_event(engine: Engine) -> None:
    repository = WorkflowRepository(engine)
    _, first, _, workflow_version = _workflow_fixture(repository)
    run = repository.create_scene_block_run(
        scene_block_version_id=first.id,
        workflow_version_id=workflow_version.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        cache_key="b" * 64,
        idempotency_key="run-concurrent",
    )
    barrier = Barrier(2)

    def write(status: SceneBlockRunStatus) -> str:
        barrier.wait()
        try:
            repository.append_scene_block_run_event(
                run_id=run.id,
                project_id=PROJECT_A,
                owner_id=OWNER_A,
                expected_state_version=0,
                status=status,
            )
        except type(WORKFLOW_VERSION_CONFLICT):
            return "conflict"
        return "written"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            executor.map(write, (SceneBlockRunStatus.PLANNING, SceneBlockRunStatus.COMPILING))
        )
    assert sorted(outcomes) == ["conflict", "written"]
    projected = repository.get_scene_block_run(run.id, PROJECT_A, OWNER_A)
    assert projected.state_version == 1


def test_composition_projection_uses_the_same_state_version_guard(engine: Engine) -> None:
    repository = WorkflowRepository(engine)
    _, _, _, workflow_version = _workflow_fixture(repository)
    run = repository.create_composition_run(
        workflow_version_id=workflow_version.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        profile=RenderProfile.PREVIEW,
        cache_key="c" * 64,
        idempotency_key="compose-1",
    )
    composing = repository.append_composition_run_event(
        run_id=run.id,
        project_id=PROJECT_A,
        owner_id=OWNER_A,
        expected_state_version=0,
        status=CompositionRunStatus.COMPOSING,
    )
    assert composing.state_version == 1
    assert composing.status is CompositionRunStatus.COMPOSING
    with pytest.raises(type(WORKFLOW_VERSION_CONFLICT)):
        repository.append_composition_run_event(
            run_id=run.id,
            project_id=PROJECT_A,
            owner_id=OWNER_A,
            expected_state_version=0,
            status=CompositionRunStatus.FAILED,
            error_code="composition_failed",
        )
