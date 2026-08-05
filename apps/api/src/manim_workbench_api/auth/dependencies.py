from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy import Engine

from manim_workbench_api.database import create_database_engine

from .errors import AUTHENTICATION_FAILED
from .models import SESSION_COOKIE_NAME, AuthSettings, SessionPrincipal, settings_from_environment
from .service import AuthService


def get_auth_engine() -> Engine:
    return create_database_engine()


def get_auth_settings() -> AuthSettings:
    return settings_from_environment()


def get_auth_service(engine: Annotated[Engine, Depends(get_auth_engine)]) -> AuthService:
    return AuthService(engine)


def get_session_principal(
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    service: Annotated[AuthService, Depends(get_auth_service)] = None,  # type: ignore[assignment]
) -> SessionPrincipal:
    if not session_token:
        raise AUTHENTICATION_FAILED
    return service.get_principal(session_token)


def get_ready_session_principal(
    principal: Annotated[SessionPrincipal, Depends(get_session_principal)],
) -> SessionPrincipal:
    if not principal.is_ready:
        from .errors import AUTHORIZATION_FAILED

        raise AUTHORIZATION_FAILED
    return principal


def get_mutating_session_principal(
    request: Request,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    service: Annotated[AuthService, Depends(get_auth_service)] = None,  # type: ignore[assignment]
    settings: Annotated[AuthSettings, Depends(get_auth_settings)] = None,  # type: ignore[assignment]
) -> SessionPrincipal:
    if not session_token or not csrf_token:
        from .errors import AUTHORIZATION_FAILED

        raise AUTHORIZATION_FAILED
    return service.authorize_mutation(
        token=session_token,
        csrf_token=csrf_token,
        origin=request.headers.get("origin"),
        settings=settings,
    )


def request_origin(request: Request) -> str | None:
    return request.headers.get("origin")
