from __future__ import annotations

from uuid import UUID

from manim_workbench_contracts import (
    Experiment,
    ExperimentCreateRequest,
    ExperimentDraft,
    ExperimentDraftUpdateRequest,
    ExperimentPage,
    ExperimentPatchProposal,
    ExperimentPatchProposalApplyRequest,
    ExperimentPatchProposalPage,
    ExperimentPatchProposalRejectRequest,
    ExperimentVersion,
    ExperimentVersionCreateRequest,
    ExperimentVersionPage,
)
from sqlalchemy import Engine

from manim_workbench_api.projects.errors import ProjectError
from manim_workbench_api.projects.repository import ProjectRepository

from .errors import PROJECT_NOT_FOUND
from .repository import ExperimentRepository


class ExperimentService:
    """Owner-scoped experiment API operations with a project collection boundary."""

    def __init__(self, engine: Engine) -> None:
        self._repository = ExperimentRepository(engine)
        self._projects = ProjectRepository(engine)

    def create_experiment(
        self,
        project_id: UUID,
        owner_id: UUID,
        request: ExperimentCreateRequest,
    ) -> Experiment:
        experiment, _draft = self._repository.create_experiment(project_id, owner_id, request)
        return experiment

    def list_experiments(
        self,
        project_id: UUID,
        owner_id: UUID,
        cursor: UUID | None,
        limit: int,
    ) -> ExperimentPage:
        self._require_project(project_id, owner_id)
        return self._repository.list_experiments(project_id, owner_id, cursor, limit)

    def get_experiment(self, experiment_id: UUID, owner_id: UUID) -> Experiment:
        return self._repository.get_experiment(experiment_id, owner_id)

    def get_draft(self, experiment_id: UUID, owner_id: UUID) -> ExperimentDraft:
        return self._repository.get_draft(experiment_id, owner_id)

    def update_draft(
        self,
        experiment_id: UUID,
        owner_id: UUID,
        request: ExperimentDraftUpdateRequest,
    ) -> ExperimentDraft:
        return self._repository.update_draft(experiment_id, owner_id, request)

    def create_version(
        self,
        experiment_id: UUID,
        owner_id: UUID,
        request: ExperimentVersionCreateRequest,
    ) -> tuple[ExperimentVersion, bool]:
        return self._repository.create_version(experiment_id, owner_id, request)

    def list_versions(
        self,
        experiment_id: UUID,
        owner_id: UUID,
        cursor: int | None,
        limit: int,
    ) -> ExperimentVersionPage:
        return self._repository.list_versions(experiment_id, owner_id, cursor, limit)

    def list_patch_proposals(
        self,
        experiment_id: UUID,
        owner_id: UUID,
        cursor: UUID | None,
        limit: int,
    ) -> ExperimentPatchProposalPage:
        return self._repository.list_patch_proposals(experiment_id, owner_id, cursor, limit)

    def apply_patch_proposal(
        self,
        experiment_id: UUID,
        proposal_id: UUID,
        owner_id: UUID,
        request: ExperimentPatchProposalApplyRequest,
    ) -> ExperimentDraft:
        return self._repository.apply_patch_proposal(experiment_id, proposal_id, owner_id, request)

    def reject_patch_proposal(
        self,
        experiment_id: UUID,
        proposal_id: UUID,
        owner_id: UUID,
        request: ExperimentPatchProposalRejectRequest,
    ) -> ExperimentPatchProposal:
        return self._repository.reject_patch_proposal(experiment_id, proposal_id, owner_id, request)

    def _require_project(self, project_id: UUID, owner_id: UUID) -> None:
        try:
            self._projects.get_project(project_id, owner_id)
        except ProjectError:
            raise PROJECT_NOT_FOUND from None
