from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine

from manim_workbench_api.auth.dependencies import get_session_principal
from manim_workbench_api.auth.models import SessionPrincipal
from manim_workbench_api.database import create_database_engine

from .service import DeliveryService


def get_delivery_engine() -> Engine:
    return create_database_engine()


def get_artifact_root() -> Path:
    return Path(os.environ.get("MANIM_WORKBENCH_ARTIFACT_ROOT", "runtime/phase5/artifacts"))


def get_delivery_service(
    engine: Annotated[Engine, Depends(get_delivery_engine)],
    artifact_root: Annotated[Path, Depends(get_artifact_root)],
) -> DeliveryService:
    return DeliveryService(engine, artifact_root)


__all__ = ["SessionPrincipal", "get_delivery_service", "get_session_principal"]
