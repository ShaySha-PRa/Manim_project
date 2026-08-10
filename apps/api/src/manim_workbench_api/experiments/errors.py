from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExperimentRepositoryError(RuntimeError):
    code: str


PROJECT_NOT_FOUND = ExperimentRepositoryError("project_not_found")
EXPERIMENT_NOT_FOUND = ExperimentRepositoryError("experiment_not_found")
EXPERIMENT_PROPOSAL_NOT_FOUND = ExperimentRepositoryError("experiment_proposal_not_found")
EXPERIMENT_REVISION_CONFLICT = ExperimentRepositoryError("experiment_revision_conflict")
EXPERIMENT_PROPOSAL_RESOLVED = ExperimentRepositoryError("experiment_proposal_resolved")
EXPERIMENT_PATCH_INVALID = ExperimentRepositoryError("experiment_patch_invalid")
