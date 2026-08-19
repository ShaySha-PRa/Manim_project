from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from manim_workbench_contracts import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    PasswordChangeRequest,
)

from .dependencies import get_auth_service, get_auth_settings
from .errors import AUTHORIZATION_FAILED, AuthError
from .models import SESSION_COOKIE_NAME, AuthSettings, AuthenticatedSession
from .service import AuthService


class StableAuthValidationRoute(APIRoute):
    """Avoid framework-shaped validation responses at the browser boundary."""

    def get_route_handler(self):  # type: ignore[no-untyped-def]
        handler = super().get_route_handler()

        async def stable_handler(request):  # type: ignore[no-untyped-def]
            try:
                return await handler(request)
            except RequestValidationError:
                return _error_response(
                    AuthError(
                        "validation_error",
                        "Request was invalid.",
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                    )
                )

        return stable_handler


router = APIRouter(tags=["auth"], route_class=StableAuthValidationRoute)
AuthDependency = Annotated[AuthService, Depends(get_auth_service)]
SettingsDependency = Annotated[AuthSettings, Depends(get_auth_settings)]
SessionCookie = Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)]
CsrfHeader = Annotated[str | None, Header(alias="X-CSRF-Token")]


def _error_response(error: AuthError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": error.code, "message": error.message}},
    )


def _set_session_cookie(response: Response, token: str, settings: AuthSettings) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response, settings: AuthSettings) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/auth/login", response_model=LoginResponse)
def login(
    request: LoginRequest,
    http_request: Request,
    response: Response,
    service: AuthDependency,
    settings: SettingsDependency,
) -> LoginResponse | JSONResponse:
    try:
        service._require_origin(http_request.headers.get("origin"), settings)
        authenticated = service.login(
            email=request.email,
            password=request.password,
            remote_addr=http_request.client.host if http_request.client else None,
            settings=settings,
        )
    except AuthError as error:
        return _error_response(error)
    _set_session_cookie(response, authenticated.token, settings)
    return LoginResponse(
        user=authenticated.principal.as_authenticated_user(),
        csrf_token=authenticated.csrf_token,
        expires_at=authenticated.principal.expires_at,
    )


@router.get("/auth/session", response_model=LoginResponse)
def session(
    response: Response,
    service: AuthDependency,
    settings: SettingsDependency,
    session_token: SessionCookie = None,
) -> LoginResponse | JSONResponse:
    authenticated: AuthenticatedSession | None = None
    if session_token:
        try:
            authenticated = service.get_session(session_token, settings)
        except AuthError:
            authenticated = None
    if authenticated is None:
        if not settings.auth_disabled:
            return _error_response(AuthError("authentication_failed", "Authentication failed.", 401))
        authenticated = service.ensure_local_dev_session(settings)
        _set_session_cookie(response, authenticated.token, settings)
    elif settings.auth_disabled and authenticated.principal.must_change_password:
        authenticated = service.ensure_local_dev_session(settings)
        _set_session_cookie(response, authenticated.token, settings)
    response.headers["Cache-Control"] = "no-store"
    return LoginResponse(
        user=authenticated.principal.as_authenticated_user(),
        csrf_token=authenticated.csrf_token,
        expires_at=authenticated.principal.expires_at,
    )


@router.post("/auth/logout", response_model=LogoutResponse)
def logout(
    http_request: Request,
    response: Response,
    service: AuthDependency,
    settings: SettingsDependency,
    session_token: SessionCookie = None,
    csrf_token: CsrfHeader = None,
) -> LogoutResponse | JSONResponse:
    if not session_token or not csrf_token:
        return _error_response(AUTHORIZATION_FAILED)
    try:
        service.logout(session_token, csrf_token, http_request.headers.get("origin"), settings)
    except AuthError as error:
        return _error_response(error)
    _clear_session_cookie(response, settings)
    return LogoutResponse(ok=True)


@router.post("/auth/change-password", response_model=LoginResponse)
def change_password(
    request: PasswordChangeRequest,
    http_request: Request,
    response: Response,
    service: AuthDependency,
    settings: SettingsDependency,
    session_token: SessionCookie = None,
    csrf_token: CsrfHeader = None,
) -> LoginResponse | JSONResponse:
    if not session_token or not csrf_token:
        return _error_response(AUTHORIZATION_FAILED)
    try:
        authenticated = service.change_password(
            token=session_token,
            csrf_token=csrf_token,
            origin=http_request.headers.get("origin"),
            current_password=request.current_password,
            new_password=request.new_password,
            settings=settings,
        )
    except AuthError as error:
        return _error_response(error)
    _set_session_cookie(response, authenticated.token, settings)
    return LoginResponse(
        user=authenticated.principal.as_authenticated_user(),
        csrf_token=authenticated.csrf_token,
        expires_at=authenticated.principal.expires_at,
    )
