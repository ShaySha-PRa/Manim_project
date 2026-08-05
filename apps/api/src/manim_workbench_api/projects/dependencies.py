from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine

from manim_workbench_api.auth.dependencies import (
    get_mutating_session_principal as get_authenticated_mutating_principal,
)
from manim_workbench_api.auth.dependencies import (
    get_ready_session_principal as get_authenticated_principal,
)
from manim_workbench_api.auth.models import SessionPrincipal
from manim_workbench_api.database import create_database_engine

__all__ = ["get_mutating_session_principal", "get_project_engine", "get_session_principal"]


def get_project_engine() -> Engine:
    return create_database_engine()


def get_session_principal(
    principal: Annotated[SessionPrincipal, Depends(get_authenticated_principal)],
) -> SessionPrincipal:
    """Require an active SessionPrincipal which has completed first-login password change."""

    return principal


def get_mutating_session_principal(
    principal: Annotated[SessionPrincipal, Depends(get_authenticated_mutating_principal)],
) -> SessionPrincipal:
    return principal
