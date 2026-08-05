from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine

from manim_workbench_api.auth.dependencies import (
    get_mutating_session_principal,
    get_ready_session_principal,
)
from manim_workbench_api.auth.models import SessionPrincipal
from manim_workbench_api.database import create_database_engine


def get_workspace_engine() -> Engine:
    return create_database_engine()


ReadyPrincipal = Annotated[SessionPrincipal, Depends(get_ready_session_principal)]
MutatingPrincipal = Annotated[SessionPrincipal, Depends(get_mutating_session_principal)]
WorkspaceEngine = Annotated[Engine, Depends(get_workspace_engine)]
