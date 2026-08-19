from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import JSONResponse
from manim_workbench_contracts.ir import UserAsset
from sqlalchemy import Engine

from manim_workbench_api.auth.models import SessionPrincipal
from manim_workbench_api.projects.dependencies import (
    get_mutating_session_principal,
    get_project_engine,
)
from manim_workbench_api.projects.errors import ProjectError

from .service import AssetError, AssetRepository, extract_constructions

router = APIRouter(tags=["assets"])
DatabaseEngine = Annotated[Engine, Depends(get_project_engine)]
Principal = Annotated[SessionPrincipal, Depends(get_mutating_session_principal)]


def _root() -> Path:
    return Path("runtime/phase10/assets").resolve()


@router.post("/projects/{project_id}/assets", response_model=UserAsset)
async def upload_asset(
    project_id: UUID,
    principal: Principal,
    engine: DatabaseEngine,
    file: Annotated[UploadFile, File()],
    content_type: Annotated[str, Form()],
) -> UserAsset | JSONResponse:
    payload = await file.read()
    try:
        extract_constructions(payload, content_type)
        filename = file.filename or "upload.bin"
        return AssetRepository(engine, _root()).save(
            project_id=project_id,
            owner_id=principal.user_id,
            filename=filename,
            content_type=content_type,
            payload=payload,
        )
    except AssetError as error:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"error": {"code": error.code, "message": error.message}},
        )
    except ProjectError as error:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": {"code": error.code, "message": error.message}},
        )
