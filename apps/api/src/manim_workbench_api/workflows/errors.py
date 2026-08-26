from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowRepositoryError(Exception):
    code: str
    message: str


WORKFLOW_NOT_FOUND = WorkflowRepositoryError(
    "workflow_not_found", "Workflow resource was not found."
)
WORKFLOW_VERSION_CONFLICT = WorkflowRepositoryError(
    "workflow_version_conflict", "The supplied parent or state version is no longer current."
)
WORKFLOW_REFERENCE_INVALID = WorkflowRepositoryError(
    "workflow_reference_invalid", "A workflow reference is outside the permitted boundary."
)
