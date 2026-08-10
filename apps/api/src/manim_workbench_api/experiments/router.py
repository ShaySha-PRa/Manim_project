from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
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

from manim_workbench_api.auth.errors import AuthError
from manim_workbench_api.auth.models import SessionPrincipal

from .dependencies import (
    get_experiment_engine,
    get_mutating_experiment_principal,
    get_ready_experiment_principal,
)
from .errors import ExperimentRepositoryError
from .service import ExperimentService

_ERRORS = {
    "project_not_found": (status.HTTP_404_NOT_FOUND, "Project was not found."),
    "experiment_not_found": (status.HTTP_404_NOT_FOUND, "Experiment was not found."),
    "experiment_proposal_not_found": (
        status.HTTP_404_NOT_FOUND,
        "Experiment patch proposal was not found.",
    ),
    "experiment_revision_conflict": (
        status.HTTP_409_CONFLICT,
        "Experiment revision is no longer current.",
    ),
    "experiment_proposal_resolved": (
        status.HTTP_409_CONFLICT,
        "Experiment patch proposal is already resolved.",
    ),
    "experiment_patch_invalid": (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "Experiment patch proposal is invalid.",
    ),
}


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


class StableExperimentRoute(APIRoute):
    """Keep experiment validation, auth, and persistence errors public-safe and stable."""

    def get_route_handler(self):  # type: ignore[no-untyped-def]
        handler = super().get_route_handler()

        async def stable_handler(request):  # type: ignore[no-untyped-def]
            try:
                return await handler(request)
            except RequestValidationError:
                return _error_response(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "validation_error",
                    "Request payload is invalid.",
                )
            except AuthError as error:
                return _error_response(error.status_code, error.code, error.message)
            except ExperimentRepositoryError as error:
                error_definition = _ERRORS.get(error.code)
                if error_definition is None:
                    raise
                status_code, message = error_definition
                return _error_response(status_code, error.code, message)

        return stable_handler


router = APIRouter(tags=["experiments"], route_class=StableExperimentRoute)
DatabaseEngine = Annotated[Engine, Depends(get_experiment_engine)]
ReadyPrincipal = Annotated[SessionPrincipal, Depends(get_ready_experiment_principal)]
MutatingPrincipal = Annotated[SessionPrincipal, Depends(get_mutating_experiment_principal)]


def _service(engine: Engine) -> ExperimentService:
    return ExperimentService(engine)


@router.post(
    "/projects/{project_id}/experiments",
    response_model=Experiment,
    status_code=status.HTTP_201_CREATED,
)
def create_experiment(
    project_id: UUID,
    request: ExperimentCreateRequest,
    principal: MutatingPrincipal,
    engine: DatabaseEngine,
) -> Experiment:
    return _service(engine).create_experiment(project_id, principal.user_id, request)


@router.get("/projects/{project_id}/experiments", response_model=ExperimentPage)
def list_experiments(
    project_id: UUID,
    principal: ReadyPrincipal,
    engine: DatabaseEngine,
    cursor: UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> ExperimentPage:
    return _service(engine).list_experiments(project_id, principal.user_id, cursor, limit)


@router.get("/experiments/{experiment_id}", response_model=Experiment)
def get_experiment(
    experiment_id: UUID,
    principal: ReadyPrincipal,
    engine: DatabaseEngine,
) -> Experiment:
    return _service(engine).get_experiment(experiment_id, principal.user_id)


@router.get("/experiments/{experiment_id}/draft", response_model=ExperimentDraft)
def get_draft(
    experiment_id: UUID,
    principal: ReadyPrincipal,
    engine: DatabaseEngine,
) -> ExperimentDraft:
    return _service(engine).get_draft(experiment_id, principal.user_id)


@router.patch("/experiments/{experiment_id}/draft", response_model=ExperimentDraft)
def update_draft(
    experiment_id: UUID,
    request: ExperimentDraftUpdateRequest,
    principal: MutatingPrincipal,
    engine: DatabaseEngine,
) -> ExperimentDraft:
    return _service(engine).update_draft(experiment_id, principal.user_id, request)


@router.post(
    "/experiments/{experiment_id}/versions",
    response_model=ExperimentVersion,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_200_OK: {
            "model": ExperimentVersion,
            "description": "Existing version with identical content.",
        }
    },
)
def create_version(
    experiment_id: UUID,
    request: ExperimentVersionCreateRequest,
    response: Response,
    principal: MutatingPrincipal,
    engine: DatabaseEngine,
) -> ExperimentVersion:
    version, created = _service(engine).create_version(experiment_id, principal.user_id, request)
    if not created:
        response.status_code = status.HTTP_200_OK
    return version


@router.get("/experiments/{experiment_id}/versions", response_model=ExperimentVersionPage)
def list_versions(
    experiment_id: UUID,
    principal: ReadyPrincipal,
    engine: DatabaseEngine,
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> ExperimentVersionPage:
    return _service(engine).list_versions(experiment_id, principal.user_id, cursor, limit)


@router.get(
    "/experiments/{experiment_id}/patch-proposals",
    response_model=ExperimentPatchProposalPage,
)
def list_patch_proposals(
    experiment_id: UUID,
    principal: ReadyPrincipal,
    engine: DatabaseEngine,
    cursor: UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> ExperimentPatchProposalPage:
    return _service(engine).list_patch_proposals(experiment_id, principal.user_id, cursor, limit)


@router.post(
    "/experiments/{experiment_id}/patch-proposals/{proposal_id}/apply",
    response_model=ExperimentDraft,
)
def apply_patch_proposal(
    experiment_id: UUID,
    proposal_id: UUID,
    request: ExperimentPatchProposalApplyRequest,
    principal: MutatingPrincipal,
    engine: DatabaseEngine,
) -> ExperimentDraft:
    return _service(engine).apply_patch_proposal(
        experiment_id,
        proposal_id,
        principal.user_id,
        request,
    )


@router.post(
    "/experiments/{experiment_id}/patch-proposals/{proposal_id}/reject",
    response_model=ExperimentPatchProposal,
)
def reject_patch_proposal(
    experiment_id: UUID,
    proposal_id: UUID,
    request: ExperimentPatchProposalRejectRequest,
    principal: MutatingPrincipal,
    engine: DatabaseEngine,
) -> ExperimentPatchProposal:
    return _service(engine).reject_patch_proposal(
        experiment_id,
        proposal_id,
        principal.user_id,
        request,
    )
