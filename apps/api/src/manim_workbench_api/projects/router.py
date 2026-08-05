from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from manim_workbench_contracts import (
    ContentPlanVersion,
    ContentPlanVersionCreateRequest,
    ContentPlanVersionPage,
    Project,
    ProjectCreateRequest,
    ProjectPage,
    ProjectUpdateRequest,
    PromptVersion,
    PromptVersionCreateRequest,
    PromptVersionPage,
)
from sqlalchemy import Engine

from manim_workbench_api.auth.errors import AuthError
from manim_workbench_api.auth.models import SessionPrincipal

from .dependencies import (
    get_mutating_session_principal,
    get_project_engine,
    get_session_principal,
)
from .errors import ProjectError
from .repository import ProjectRepository
from .service import ProjectService


class StableValidationRoute(APIRoute):
    def get_route_handler(self):  # type: ignore[no-untyped-def]
        original_handler = super().get_route_handler()

        async def stable_validation_handler(request):  # type: ignore[no-untyped-def]
            try:
                return await original_handler(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    content={
                        "error": {
                            "code": "validation_error",
                            "message": "Request payload is invalid.",
                        }
                    },
                )
            except AuthError as error:
                return JSONResponse(
                    status_code=error.status_code,
                    content={"error": {"code": error.code, "message": error.message}},
                )

        return stable_validation_handler


router = APIRouter(tags=["projects"], route_class=StableValidationRoute)
DatabaseEngine = Annotated[Engine, Depends(get_project_engine)]
Principal = Annotated[SessionPrincipal, Depends(get_session_principal)]
MutatingPrincipal = Annotated[SessionPrincipal, Depends(get_mutating_session_principal)]


def _service(engine: Engine) -> ProjectService:
    return ProjectService(ProjectRepository(engine))


@router.get("/projects", response_model=ProjectPage)
def list_projects(
    principal: Principal,
    engine: DatabaseEngine,
    cursor: UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> ProjectPage:
    return _service(engine).list_projects(principal.user_id, cursor, limit)


@router.post("/projects", response_model=Project, status_code=status.HTTP_201_CREATED)
def create_project(
    request: ProjectCreateRequest, principal: MutatingPrincipal, engine: DatabaseEngine
) -> Project:
    return _service(engine).create_project(principal.user_id, request)


@router.get("/projects/{project_id}", response_model=Project)
def get_project(
    project_id: UUID, principal: Principal, engine: DatabaseEngine
) -> Project | JSONResponse:
    try:
        return _service(engine).get_project(project_id, principal.user_id)
    except ProjectError as error:
        return error.response()


@router.patch("/projects/{project_id}", response_model=Project)
def update_project(
    project_id: UUID,
    request: ProjectUpdateRequest,
    principal: MutatingPrincipal,
    engine: DatabaseEngine,
) -> Project | JSONResponse:
    try:
        return _service(engine).update_project(project_id, principal.user_id, request)
    except ProjectError as error:
        return error.response()


@router.get("/projects/{project_id}/prompt-versions", response_model=PromptVersionPage)
def list_prompt_versions(
    project_id: UUID,
    principal: Principal,
    engine: DatabaseEngine,
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> PromptVersionPage | JSONResponse:
    try:
        return _service(engine).list_prompt_versions(project_id, principal.user_id, cursor, limit)
    except ProjectError as error:
        return error.response()


@router.post(
    "/projects/{project_id}/prompt-versions",
    response_model=PromptVersion,
    status_code=status.HTTP_201_CREATED,
)
def create_prompt_version(
    project_id: UUID,
    request: PromptVersionCreateRequest,
    principal: MutatingPrincipal,
    engine: DatabaseEngine,
) -> PromptVersion | JSONResponse:
    try:
        return _service(engine).create_prompt_version(project_id, principal.user_id, request)
    except ProjectError as error:
        return error.response()


@router.get("/projects/{project_id}/content-plan-versions", response_model=ContentPlanVersionPage)
def list_content_plan_versions(
    project_id: UUID,
    principal: Principal,
    engine: DatabaseEngine,
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> ContentPlanVersionPage | JSONResponse:
    try:
        return _service(engine).list_content_plan_versions(
            project_id, principal.user_id, cursor, limit
        )
    except ProjectError as error:
        return error.response()


@router.post(
    "/projects/{project_id}/content-plan-versions",
    response_model=ContentPlanVersion,
    status_code=status.HTTP_201_CREATED,
)
def create_content_plan_version(
    project_id: UUID,
    request: ContentPlanVersionCreateRequest,
    principal: MutatingPrincipal,
    engine: DatabaseEngine,
) -> ContentPlanVersion | JSONResponse:
    try:
        return _service(engine).create_content_plan_version(project_id, principal.user_id, request)
    except ProjectError as error:
        return error.response()
