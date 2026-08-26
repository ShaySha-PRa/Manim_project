from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from manim_workbench_api.workflows import WorkflowValidationError, validate_linear_workflow
from manim_workbench_contracts import (
    GlobalBrief,
    Language,
    SceneBlockVersion,
    ScenePipelineMode,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeKind,
    WorkflowStylePreset,
)

OWNER = UUID("00000000-0000-0000-0000-000000000001")
PROJECT = UUID("10000000-0000-0000-0000-000000000001")
WORKFLOW = UUID("20000000-0000-0000-0000-000000000001")


def _brief() -> GlobalBrief:
    return GlobalBrief(
        title="Workflow",
        language=Language.EN_US,
        target_duration_seconds=120,
        style_preset=WorkflowStylePreset.PRESENTATION,
        background="#111111",
        palette=("#ffffff",),
    )


def _scene(*, duration: int = 30, workflow_id: UUID = WORKFLOW) -> SceneBlockVersion:
    return SceneBlockVersion(
        id=uuid4(),
        workflow_id=workflow_id,
        project_id=PROJECT,
        owner_id=OWNER,
        version=1,
        parent_version_id=None,
        title="Scene",
        prompt="Explain a scientific idea.",
        pipeline_mode=ScenePipelineMode.AUTO,
        target_duration_seconds=duration,
        created_at=datetime.now(timezone.utc),
    )


def _graph(
    scenes: tuple[SceneBlockVersion, ...],
) -> tuple[tuple[WorkflowNode, ...], tuple[WorkflowEdge, ...]]:
    nodes = tuple(
        WorkflowNode(id=uuid4(), kind=WorkflowNodeKind.SCENE, scene_block_version_id=item.id)
        for item in scenes
    ) + (
        WorkflowNode(id=uuid4(), kind=WorkflowNodeKind.COMPOSE),
        WorkflowNode(id=uuid4(), kind=WorkflowNodeKind.EXPORT),
    )
    edges = tuple(
        WorkflowEdge(source_node_id=nodes[index].id, target_node_id=nodes[index + 1].id)
        for index in range(len(nodes) - 1)
    )
    return nodes, edges


def test_accepts_exact_linear_scene_compose_export_graph() -> None:
    scenes = (_scene(), _scene(), _scene())
    nodes, edges = _graph(scenes)
    validate_linear_workflow(
        global_brief=_brief(), nodes=nodes, edges=edges, scene_versions=scenes
    )


@pytest.mark.parametrize("shape", ["branch", "cycle", "multiple_output", "wrong_order"])
def test_rejects_every_non_linear_graph_shape(shape: str) -> None:
    scenes = (_scene(), _scene(), _scene())
    nodes, edges = _graph(scenes)
    if shape == "branch":
        edges = edges[:-1] + (WorkflowEdge(source_node_id=nodes[0].id, target_node_id=nodes[2].id),)
    elif shape == "cycle":
        edges = edges[:-1] + (
            WorkflowEdge(source_node_id=nodes[-1].id, target_node_id=nodes[0].id),
        )
    elif shape == "multiple_output":
        edges = edges[:-1] + (
            WorkflowEdge(source_node_id=nodes[1].id, target_node_id=nodes[-1].id),
        )
    else:
        nodes = (nodes[0], nodes[-2], *nodes[1:-2], nodes[-1])
    with pytest.raises(WorkflowValidationError) as caught:
        validate_linear_workflow(
            global_brief=_brief(), nodes=nodes, edges=edges, scene_versions=scenes
        )
    assert caught.value.code.startswith("workflow_")


def test_rejects_duplicate_scene_cross_boundary_and_total_duration() -> None:
    first = _scene(duration=120)
    second = _scene(duration=120)
    nodes, edges = _graph((first, second))
    duplicate_nodes = (
        nodes[0],
        nodes[1].model_copy(update={"scene_block_version_id": first.id}),
        *nodes[2:],
    )
    with pytest.raises(WorkflowValidationError, match="distinct version"):
        validate_linear_workflow(
            global_brief=_brief(),
            nodes=duplicate_nodes,
            edges=edges,
            scene_versions=(first, second),
        )

    foreign = _scene(workflow_id=uuid4())
    foreign_nodes, foreign_edges = _graph((first, foreign))
    with pytest.raises(WorkflowValidationError, match="one workflow"):
        validate_linear_workflow(
            global_brief=_brief(),
            nodes=foreign_nodes,
            edges=foreign_edges,
            scene_versions=(first, foreign),
        )

    long_scenes = tuple(_scene(duration=120) for _ in range(6))
    long_nodes, long_edges = _graph(long_scenes)
    with pytest.raises(WorkflowValidationError) as caught:
        validate_linear_workflow(
            global_brief=_brief(),
            nodes=long_nodes,
            edges=long_edges,
            scene_versions=long_scenes,
        )
    assert caught.value.code == "workflow_duration_exceeded"
