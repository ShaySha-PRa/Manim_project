from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from manim_workbench_contracts import (
    CompositionRun,
    SceneBlockRun,
    SceneBlockVersion,
    SceneRunProvenance,
    VideoWorkflowVersion,
)
from sqlalchemy import Engine

from manim_workbench_api.assets.scientific import AssetIngestError
from manim_workbench_api.auth.models import SessionPrincipal
from manim_workbench_api.projects.router import StableValidationRoute

from .dependencies import (
    get_mutating_session_principal,
    get_project_engine,
    get_session_principal,
)
from .errors import (
    WORKFLOW_NOT_FOUND,
    WORKFLOW_REFERENCE_INVALID,
    WorkflowRepositoryError,
)
from .events import WorkflowEventCursor, WorkflowEventService
from .models import (
    CompositionRunCreateRequest,
    SceneBlockCreateRequest,
    SceneBlockCreation,
    SceneBlockRecord,
    SceneBlockVersionCreateRequest,
    SceneBlockVersionDetail,
    SceneRunCreateRequest,
    ScientificAssetRecord,
    ScientificCsvAssetCreateRequest,
    VideoWorkflowRecord,
    WorkflowVersionCreateRequest,
)
from .queue import WorkflowTaskNotifier
from .runtime import get_redis_workflow_task_notifier
from .service import WorkflowService

router = APIRouter(tags=["video-workflows"], route_class=StableValidationRoute)
DatabaseEngine = Annotated[Engine, Depends(get_project_engine)]
Principal = Annotated[SessionPrincipal, Depends(get_session_principal)]
MutatingPrincipal = Annotated[SessionPrincipal, Depends(get_mutating_session_principal)]
TaskNotifier = Annotated[WorkflowTaskNotifier | None, Depends(get_redis_workflow_task_notifier)]
LastEventId = Annotated[str | None, Header(alias="Last-Event-ID")]


def _service(
    engine: Engine, notifier: WorkflowTaskNotifier | None = None
) -> WorkflowService:
    return WorkflowService(engine, notifier)


def _error(error: WorkflowRepositoryError) -> JSONResponse:
    hidden = error in {WORKFLOW_NOT_FOUND, WORKFLOW_REFERENCE_INVALID}
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND if hidden else status.HTTP_409_CONFLICT,
        content={"error": {"code": error.code, "message": error.message}},
    )


@router.post(
    "/projects/{project_id}/video-workflows",
    response_model=VideoWorkflowRecord,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow(
    project_id: UUID, principal: MutatingPrincipal, engine: DatabaseEngine
) -> VideoWorkflowRecord | JSONResponse:
    service = _service(engine)
    try:
        workflow_id = service.repository.create_workflow(project_id, principal.user_id)
        return service.repository.get_workflow(workflow_id, principal.user_id)
    except WorkflowRepositoryError as error:
        return _error(error)


@router.post(
    "/projects/{project_id}/scientific-assets/csv",
    response_model=ScientificAssetRecord,
    status_code=status.HTTP_201_CREATED,
)
def create_scientific_csv_asset(
    project_id: UUID,
    request: ScientificCsvAssetCreateRequest,
    principal: MutatingPrincipal,
    engine: DatabaseEngine,
) -> ScientificAssetRecord | JSONResponse:
    try:
        return _service(engine).create_csv_asset(
            project_id, principal.user_id, request.csv_text
        )
    except AssetIngestError as error:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"error": {"code": "asset_invalid", "message": str(error)}},
        )
    except WorkflowRepositoryError as error:
        return _error(error)


@router.get("/video-workflows/{workflow_id}", response_model=VideoWorkflowRecord)
def get_workflow(
    workflow_id: UUID, principal: Principal, engine: DatabaseEngine
) -> VideoWorkflowRecord | JSONResponse:
    try:
        return _service(engine).repository.get_workflow(workflow_id, principal.user_id)
    except WorkflowRepositoryError as error:
        return _error(error)


@router.get(
    "/video-workflows/{workflow_id}/versions", response_model=list[VideoWorkflowVersion]
)
def list_workflow_versions(
    workflow_id: UUID, principal: Principal, engine: DatabaseEngine
) -> tuple[VideoWorkflowVersion, ...] | JSONResponse:
    try:
        return _service(engine).repository.list_workflow_versions(
            workflow_id, principal.user_id
        )
    except WorkflowRepositoryError as error:
        return _error(error)


@router.post(
    "/video-workflows/{workflow_id}/versions",
    response_model=VideoWorkflowVersion,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_version(
    workflow_id: UUID,
    request: WorkflowVersionCreateRequest,
    principal: MutatingPrincipal,
    engine: DatabaseEngine,
) -> VideoWorkflowVersion | JSONResponse:
    try:
        return _service(engine).append_workflow_version(
            workflow_id, principal.user_id, request
        )
    except WorkflowRepositoryError as error:
        return _error(error)


@router.get("/workflow-versions/{version_id}", response_model=VideoWorkflowVersion)
def get_workflow_version(
    version_id: UUID, principal: Principal, engine: DatabaseEngine
) -> VideoWorkflowVersion | JSONResponse:
    try:
        return _service(engine).get_workflow_version_for_owner(
            version_id, principal.user_id
        )
    except WorkflowRepositoryError as error:
        return _error(error)


@router.post(
    "/video-workflows/{workflow_id}/scene-blocks",
    response_model=SceneBlockCreation,
    status_code=status.HTTP_201_CREATED,
)
def create_scene_block(
    workflow_id: UUID,
    request: SceneBlockCreateRequest,
    principal: MutatingPrincipal,
    engine: DatabaseEngine,
) -> SceneBlockCreation | JSONResponse:
    try:
        return _service(engine).create_scene_block(workflow_id, principal.user_id, request)
    except WorkflowRepositoryError as error:
        return _error(error)


@router.get("/scene-blocks/{block_id}", response_model=SceneBlockRecord)
def get_scene_block(
    block_id: UUID, principal: Principal, engine: DatabaseEngine
) -> SceneBlockRecord | JSONResponse:
    try:
        return _service(engine).repository.get_scene_block(block_id, principal.user_id)
    except WorkflowRepositoryError as error:
        return _error(error)


@router.get(
    "/scene-blocks/{block_id}/versions", response_model=list[SceneBlockVersion]
)
def list_scene_block_versions(
    block_id: UUID, principal: Principal, engine: DatabaseEngine
) -> tuple[SceneBlockVersion, ...] | JSONResponse:
    try:
        return _service(engine).repository.list_scene_block_versions(
            block_id, principal.user_id
        )
    except WorkflowRepositoryError as error:
        return _error(error)


@router.get(
    "/scene-block-versions/{version_id}", response_model=SceneBlockVersionDetail
)
def get_scene_block_version(
    version_id: UUID, principal: Principal, engine: DatabaseEngine
) -> SceneBlockVersionDetail | JSONResponse:
    try:
        return _service(engine).repository.get_scene_block_version_detail(
            version_id, principal.user_id
        )
    except WorkflowRepositoryError as error:
        return _error(error)


@router.post(
    "/scene-blocks/{block_id}/versions",
    response_model=SceneBlockVersion,
    status_code=status.HTTP_201_CREATED,
)
def create_scene_block_version(
    block_id: UUID,
    request: SceneBlockVersionCreateRequest,
    principal: MutatingPrincipal,
    engine: DatabaseEngine,
) -> SceneBlockVersion | JSONResponse:
    try:
        return _service(engine).append_scene_block_version(
            block_id, principal.user_id, request
        )
    except WorkflowRepositoryError as error:
        return _error(error)


@router.post(
    "/scene-block-versions/{version_id}/runs",
    response_model=SceneBlockRun,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_scene_run(
    version_id: UUID,
    request: SceneRunCreateRequest,
    principal: MutatingPrincipal,
    engine: DatabaseEngine,
    notifier: TaskNotifier,
) -> SceneBlockRun | JSONResponse:
    try:
        return _service(engine, notifier).submit_scene_run(
            version_id, principal.user_id, request
        )
    except WorkflowRepositoryError as error:
        return _error(error)


@router.get("/scene-block-runs/{run_id}", response_model=SceneBlockRun)
def get_scene_run(
    run_id: UUID, principal: Principal, engine: DatabaseEngine
) -> SceneBlockRun | JSONResponse:
    try:
        return _service(engine).get_scene_run_for_owner(run_id, principal.user_id)
    except WorkflowRepositoryError as error:
        return _error(error)


@router.get(
    "/scene-block-runs/{run_id}/provenance",
    response_model=SceneRunProvenance,
)
def get_scene_run_provenance(
    run_id: UUID, principal: Principal, engine: DatabaseEngine
) -> SceneRunProvenance | JSONResponse:
    try:
        return _service(engine).get_scene_provenance_for_owner(run_id, principal.user_id)
    except WorkflowRepositoryError as error:
        return _error(error)


@router.get("/scene-block-runs/{run_id}/events", response_model=None)
def get_scene_run_events(
    run_id: UUID,
    principal: Principal,
    engine: DatabaseEngine,
    last_event_id: LastEventId = None,
) -> StreamingResponse | JSONResponse:
    events = WorkflowEventService(engine)
    try:
        cursor = WorkflowEventCursor.parse(last_event_id)
        events.scene_events(run_id, principal.user_id, cursor)
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": {
                    "code": "invalid_event_cursor",
                    "message": "Event cursor was invalid.",
                }
            },
        )
    except WorkflowRepositoryError as error:
        return _error(error)
    return StreamingResponse(
        events.scene_event_stream(run_id, principal.user_id, cursor),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/workflow-versions/{version_id}/composition-runs",
    response_model=CompositionRun,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_composition_run(
    version_id: UUID,
    request: CompositionRunCreateRequest,
    principal: MutatingPrincipal,
    engine: DatabaseEngine,
    notifier: TaskNotifier,
) -> CompositionRun | JSONResponse:
    try:
        return _service(engine, notifier).submit_composition_run(
            version_id, principal.user_id, request
        )
    except WorkflowRepositoryError as error:
        return _error(error)


@router.get("/composition-runs/{run_id}", response_model=CompositionRun)
def get_composition_run(
    run_id: UUID, principal: Principal, engine: DatabaseEngine
) -> CompositionRun | JSONResponse:
    try:
        return _service(engine).get_composition_run_for_owner(run_id, principal.user_id)
    except WorkflowRepositoryError as error:
        return _error(error)


@router.get("/composition-runs/{run_id}/events", response_model=None)
def get_composition_run_events(
    run_id: UUID,
    principal: Principal,
    engine: DatabaseEngine,
    last_event_id: LastEventId = None,
) -> StreamingResponse | JSONResponse:
    events = WorkflowEventService(engine)
    try:
        cursor = WorkflowEventCursor.parse(last_event_id)
        events.composition_events(run_id, principal.user_id, cursor)
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": {
                    "code": "invalid_event_cursor",
                    "message": "Event cursor was invalid.",
                }
            },
        )
    except WorkflowRepositoryError as error:
        return _error(error)
    return StreamingResponse(
        events.composition_event_stream(run_id, principal.user_id, cursor),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/composition-runs/{run_id}/artifact", response_model=None)
def get_composition_artifact(
    run_id: UUID, principal: Principal, engine: DatabaseEngine
) -> RedirectResponse | JSONResponse:
    try:
        run = _service(engine).get_composition_run_for_owner(run_id, principal.user_id)
    except WorkflowRepositoryError as error:
        return _error(error)
    if run.artifact_id is None:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {
                    "code": "composition_artifact_not_ready",
                    "message": "Composition artifact is not ready.",
                }
            },
        )
    return RedirectResponse(
        url=f"/api/v1/artifacts/{run.artifact_id}/download",
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
