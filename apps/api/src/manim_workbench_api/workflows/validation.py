from __future__ import annotations

from dataclasses import dataclass

from manim_workbench_contracts import (
    GlobalBrief,
    SceneBlockVersion,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeKind,
)


@dataclass(frozen=True)
class WorkflowValidationError(Exception):
    code: str
    message: str


def validate_linear_workflow(
    *,
    global_brief: GlobalBrief,
    nodes: tuple[WorkflowNode, ...],
    edges: tuple[WorkflowEdge, ...],
    scene_versions: tuple[SceneBlockVersion, ...],
) -> None:
    """Reject every graph shape outside Scene+ -> Compose -> Export."""

    expected_kinds = (
        *(WorkflowNodeKind.SCENE for _ in range(len(nodes) - 2)),
        WorkflowNodeKind.COMPOSE,
        WorkflowNodeKind.EXPORT,
    )
    actual_kinds = tuple(node.kind for node in nodes)
    if actual_kinds != expected_kinds:
        raise WorkflowValidationError(
            "workflow_node_order_invalid",
            "Nodes must be ordered as 2-8 scenes followed by compose and export.",
        )

    expected_edges = tuple(
        (nodes[index].id, nodes[index + 1].id) for index in range(len(nodes) - 1)
    )
    actual_edges = tuple((edge.source_node_id, edge.target_node_id) for edge in edges)
    if actual_edges != expected_edges:
        raise WorkflowValidationError(
            "workflow_graph_not_linear",
            "Edges must connect each ordered node exactly once without branches or cycles.",
        )

    referenced_ids = tuple(
        node.scene_block_version_id
        for node in nodes
        if node.kind is WorkflowNodeKind.SCENE
    )
    if len(set(referenced_ids)) != len(referenced_ids):
        raise WorkflowValidationError(
            "workflow_scene_reused", "Each scene position must reference a distinct version."
        )
    versions_by_id = {item.id: item for item in scene_versions}
    if set(referenced_ids) != set(versions_by_id):
        raise WorkflowValidationError(
            "workflow_scene_reference_invalid",
            "Every scene node must resolve to exactly one permitted SceneBlockVersion.",
        )

    boundary = {
        (item.workflow_id, item.project_id, item.owner_id) for item in scene_versions
    }
    if len(boundary) != 1:
        raise WorkflowValidationError(
            "workflow_scene_boundary_invalid",
            "All scene versions must belong to one workflow, project, and owner.",
        )

    total_duration = sum(item.target_duration_seconds for item in scene_versions)
    if total_duration > 600:
        raise WorkflowValidationError(
            "workflow_duration_exceeded", "Scene target durations may total at most 600 seconds."
        )
    if global_brief.target_duration_seconds > 600:
        raise WorkflowValidationError(
            "workflow_duration_exceeded", "Workflow target duration may be at most 600 seconds."
        )
