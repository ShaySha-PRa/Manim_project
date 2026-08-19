from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from manim_workbench_contracts import AuthenticatedUser

SESSION_COOKIE_NAME = "manim_workbench_session"
DEFAULT_SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
MIN_SESSION_MAX_AGE_SECONDS = 5 * 60
MAX_SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class AuthSettings:
    allowed_origins: frozenset[str]
    cookie_secure: bool
    session_max_age_seconds: int = DEFAULT_SESSION_MAX_AGE_SECONDS
    auth_disabled: bool = False

    def __post_init__(self) -> None:
        if not self.allowed_origins or "*" in self.allowed_origins:
            raise ValueError("allowed_origins must be a non-empty explicit allowlist")
        if (
            not MIN_SESSION_MAX_AGE_SECONDS
            <= self.session_max_age_seconds
            <= MAX_SESSION_MAX_AGE_SECONDS
        ):
            raise ValueError("session_max_age_seconds is outside the allowed range")


@dataclass(frozen=True, slots=True)
class SessionPrincipal:
    """Authenticated identity derived from an opaque, server-side session."""

    user_id: UUID
    email: str
    created_at: datetime
    must_change_password: bool
    session_id: UUID
    expires_at: datetime

    @property
    def is_ready(self) -> bool:
        return not self.must_change_password

    def as_authenticated_user(self) -> AuthenticatedUser:
        return AuthenticatedUser(
            id=self.user_id,
            email=self.email,
            must_change_password=self.must_change_password,
            created_at=self.created_at,
        )


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    principal: SessionPrincipal
    token: str
    csrf_token: str


def settings_from_environment() -> AuthSettings:
    raw_origins = os.environ.get("MANIM_WORKBENCH_ALLOWED_ORIGINS", "http://localhost:3000")
    allowed_origins = frozenset(
        origin.strip().rstrip("/") for origin in raw_origins.split(",") if origin.strip()
    )
    cookie_secure = os.environ.get("MANIM_WORKBENCH_COOKIE_SECURE", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    raw_age = os.environ.get("MANIM_WORKBENCH_SESSION_MAX_AGE_SECONDS")
    session_max_age_seconds = int(raw_age) if raw_age else DEFAULT_SESSION_MAX_AGE_SECONDS
    raw_auth = os.environ.get("MANIM_WORKBENCH_AUTH_DISABLED", "true").lower()
    return AuthSettings(
        allowed_origins=allowed_origins,
        cookie_secure=cookie_secure,
        session_max_age_seconds=session_max_age_seconds,
        auth_disabled=raw_auth not in {"0", "false", "no"},
    )
