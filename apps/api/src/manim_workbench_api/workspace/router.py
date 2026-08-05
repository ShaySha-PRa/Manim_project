from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.routing import APIRoute
from manim_workbench_contracts import (
    ArtifactDescriptor,
    CodeGenerationRequest,
    CodeGenerationResponse,
    ContentPlanGenerationRequest,
    ContentPlanGenerationResponse,
    RenderJobSubmission,
    WorkspaceCodeGenerationRequest,
    WorkspaceContentPlanGenerationRequest,
    WorkspaceRenderJobSubmission,
)
from sqlalchemy import text

from manim_workbench_api.auth.errors import AuthError
from manim_workbench_api.code_generation.dependencies import (
    get_code_generation_provider,
    get_code_generation_renderer,
)
from manim_workbench_api.code_generation.errors import CodeGenerationError
from manim_workbench_api.code_generation.models import CandidateRenderer, CodeGenerationProvider
from manim_workbench_api.code_generation.repository import CodeGenerationRepository
from manim_workbench_api.code_generation.router import _ERROR_STATUS as CODE_ERROR_STATUS
from manim_workbench_api.code_generation.service import CodeGenerationService
from manim_workbench_api.content_plans.dependencies import get_content_plan_provider
from manim_workbench_api.content_plans.errors import ContentPlanError, ContentPlanErrorCode
from manim_workbench_api.content_plans.models import ContentPlanProvider
from manim_workbench_api.content_plans.repository import ContentPlanRepository
from manim_workbench_api.content_plans.router import ERROR_STATUS as CONTENT_ERROR_STATUS
from manim_workbench_api.content_plans.service import ContentPlanService
from manim_workbench_api.jobs.dependencies import (
    JobSignalPublisher,
    get_job_signal_publisher,
)
from manim_workbench_api.jobs.errors import JobError
from manim_workbench_api.jobs.models import JobResponse
from manim_workbench_api.jobs.repository import JobRepository
from manim_workbench_api.jobs.service import JobService
from manim_workbench_api.projects.errors import ProjectError
from manim_workbench_api.projects.repository import ProjectRepository

from .dependencies import MutatingPrincipal, ReadyPrincipal, WorkspaceEngine


class StableWorkspaceRoute(APIRoute):
    def get_route_handler(self):  # type: ignore[no-untyped-def]
        handler = super().get_route_handler()

        async def stable_handler(request):  # type: ignore[no-untyped-def]
            try:
                return await handler(request)
            except RequestValidationError:
                return _error(422, "validation_error", "Request was invalid.")
            except AuthError as error:
                return _error(error.status_code, error.code, error.message)

        return stable_handler


router = APIRouter(tags=["workspace"], route_class=StableWorkspaceRoute)
ContentProvider = Annotated[ContentPlanProvider, Depends(get_content_plan_provider)]
CodeProvider = Annotated[CodeGenerationProvider, Depends(get_code_generation_provider)]
Renderer = Annotated[CandidateRenderer, Depends(get_code_generation_renderer)]
Publisher = Annotated[JobSignalPublisher, Depends(get_job_signal_publisher)]

_CONTENT_ERROR_MESSAGES = {
    ContentPlanErrorCode.PROMPT_VERSION_NOT_FOUND: "Prompt version was not found.",
    ContentPlanErrorCode.OWNERSHIP_MISMATCH: "Prompt version was not found.",
    ContentPlanErrorCode.CONTENT_PLAN_SEMANTIC_ERROR: (
        "Content plan generation needs clarification."
    ),
}


def _error(status_code: int, code: str, message: str, stage: str | None = None) -> JSONResponse:
    detail: dict[str, str] = {"code": code, "message": message}
    if stage:
        detail["stage"] = stage
    return JSONResponse(status_code=status_code, content={"error": detail})


def _require_project(engine, project_id: UUID, owner_id: UUID) -> JSONResponse | None:  # type: ignore[no-untyped-def]
    try:
        ProjectRepository(engine).get_project(project_id, owner_id)
    except ProjectError:
        return _error(404, "project_not_found", "Project was not found.")
    return None


@router.post(
    "/workspace/projects/{project_id}/content-plans/generate",
    response_model=ContentPlanGenerationResponse,
)
def generate_content_plan(
    project_id: UUID,
    request: WorkspaceContentPlanGenerationRequest,
    principal: MutatingPrincipal,
    engine: WorkspaceEngine,
    provider: ContentProvider,
) -> ContentPlanGenerationResponse | JSONResponse:
    if error := _require_project(engine, project_id, principal.user_id):
        return error
    internal = ContentPlanGenerationRequest(
        project_id=project_id,
        owner_id=principal.user_id,
        **request.model_dump(),
    )
    try:
        return ContentPlanService(ContentPlanRepository(engine), provider).generate(internal)
    except ContentPlanError as error:
        code = error.code
        if code is ContentPlanErrorCode.OWNERSHIP_MISMATCH:
            code = ContentPlanErrorCode.PROMPT_VERSION_NOT_FOUND
        return _error(
            CONTENT_ERROR_STATUS[code],
            code.value,
            _CONTENT_ERROR_MESSAGES.get(code, "Content plan generation failed."),
            "content_plan",
        )


@router.post(
    "/workspace/projects/{project_id}/code-generations",
    response_model=CodeGenerationResponse,
)
def generate_code(
    project_id: UUID,
    request: WorkspaceCodeGenerationRequest,
    principal: MutatingPrincipal,
    engine: WorkspaceEngine,
    provider: CodeProvider,
    renderer: Renderer,
) -> CodeGenerationResponse | JSONResponse:
    if error := _require_project(engine, project_id, principal.user_id):
        return error
    internal = CodeGenerationRequest(
        project_id=project_id,
        owner_id=principal.user_id,
        **request.model_dump(),
    )
    try:
        return CodeGenerationService(CodeGenerationRepository(engine), provider, renderer).generate(
            internal
        )
    except CodeGenerationError as error:
        return _error(
            CODE_ERROR_STATUS[error.code],
            error.code.value,
            "Code generation failed.",
            "code_generation",
        )


@router.post(
    "/workspace/projects/{project_id}/render-jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_render_job(
    project_id: UUID,
    request: WorkspaceRenderJobSubmission,
    principal: MutatingPrincipal,
    engine: WorkspaceEngine,
    publisher: Publisher,
) -> JobResponse | JSONResponse:
    if error := _require_project(engine, project_id, principal.user_id):
        return error
    try:
        CodeGenerationRepository(engine).get_version(
            request.code_version_id,
            project_id=project_id,
            owner_id=principal.user_id,
        )
    except CodeGenerationError:
        return _error(404, "code_version_not_found", "Code version was not found.")
    submission = RenderJobSubmission(
        project_id=project_id,
        owner_id=principal.user_id,
        **request.model_dump(),
    )
    try:
        job, created = JobService(JobRepository(engine), publisher).submit(submission)
    except JobError as error:
        return error.response()
    if not created:
        return JSONResponse(status_code=200, content=job.model_dump(mode="json"))
    return job


def _owned_job(engine, job_id: UUID, owner_id: UUID):  # type: ignore[no-untyped-def]
    record = JobRepository(engine).get(job_id)
    if record is None or record.owner_id != owner_id:
        return None
    return record


@router.get("/workspace/render-jobs/{job_id}", response_model=JobResponse)
def get_render_job(
    job_id: UUID,
    principal: ReadyPrincipal,
    engine: WorkspaceEngine,
    publisher: Publisher,
) -> JobResponse | JSONResponse:
    if _owned_job(engine, job_id, principal.user_id) is None:
        return _error(404, "render_job_not_found", "Render job was not found.")
    return JobService(JobRepository(engine), publisher).get(job_id)


@router.post("/workspace/render-jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_render_job(
    job_id: UUID,
    principal: MutatingPrincipal,
    engine: WorkspaceEngine,
    publisher: Publisher,
) -> JobResponse | JSONResponse:
    if _owned_job(engine, job_id, principal.user_id) is None:
        return _error(404, "render_job_not_found", "Render job was not found.")
    try:
        return JobService(JobRepository(engine), publisher).cancel(job_id)
    except JobError as error:
        return error.response()


@router.get(
    "/workspace/render-jobs/{job_id}/artifacts",
    response_model=tuple[ArtifactDescriptor, ...],
)
def list_artifacts(
    job_id: UUID,
    principal: ReadyPrincipal,
    engine: WorkspaceEngine,
) -> tuple[ArtifactDescriptor, ...] | JSONResponse:
    if _owned_job(engine, job_id, principal.user_id) is None:
        return _error(404, "render_job_not_found", "Render job was not found.")
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, render_job_id, kind, sha256, byte_size FROM artifacts "
                "WHERE render_job_id = :job_id AND owner_id = :owner_id ORDER BY kind"
            ),
            {"job_id": str(job_id), "owner_id": str(principal.user_id)},
        ).mappings()
        return tuple(
            ArtifactDescriptor(
                id=UUID(str(row["id"])),
                render_job_id=UUID(str(row["render_job_id"])),
                kind=str(row["kind"]),
                sha256=str(row["sha256"]),
                byte_size=int(row["byte_size"]),
                preview_url=f"/api/v1/artifacts/{row['id']}",
                download_url=f"/api/v1/artifacts/{row['id']}/download",
            )
            for row in rows
        )


@router.get("/workspace/code-versions/{code_version_id}/source", response_model=None)
def read_code_source(
    code_version_id: UUID,
    principal: ReadyPrincipal,
    engine: WorkspaceEngine,
    download: bool = Query(default=False),
) -> PlainTextResponse | JSONResponse:
    with engine.connect() as connection:
        source = connection.execute(
            text("SELECT source_code FROM code_versions WHERE id = :id AND owner_id = :owner_id"),
            {"id": str(code_version_id), "owner_id": str(principal.user_id)},
        ).scalar_one_or_none()
    if source is None:
        return _error(404, "code_version_not_found", "Code version was not found.")
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"}
    if download:
        headers["Content-Disposition"] = 'attachment; filename="GeneratedScene.py"'
    return PlainTextResponse(str(source), headers=headers)
