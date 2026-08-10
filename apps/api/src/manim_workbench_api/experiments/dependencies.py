from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine

from manim_workbench_api.auth.dependencies import (
    get_mutating_session_principal as get_authenticated_mutating_principal,
)
from manim_workbench_api.auth.dependencies import (
    get_ready_session_principal as get_authenticated_ready_principal,
)
from manim_workbench_api.auth.models import SessionPrincipal
from manim_workbench_api.database import create_database_engine


def get_experiment_engine() -> Engine:
    return create_database_engine()


def get_ready_experiment_principal(
    principal: Annotated[SessionPrincipal, Depends(get_authenticated_ready_principal)],
) -> SessionPrincipal:
    """Require the existing ready-session policy for experiment reads."""

    return principal


def get_mutating_experiment_principal(
    principal: Annotated[SessionPrincipal, Depends(get_authenticated_mutating_principal)],
) -> SessionPrincipal:
    """Require the existing session-bound Origin and CSRF policy for experiment writes."""

    return principal
