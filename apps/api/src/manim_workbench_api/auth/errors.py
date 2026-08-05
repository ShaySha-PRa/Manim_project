from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthError(Exception):
    code: str
    message: str
    status_code: int


AUTHENTICATION_FAILED = AuthError("authentication_failed", "Authentication failed.", 401)
AUTHORIZATION_FAILED = AuthError("authorization_failed", "Request was not authorized.", 403)
LOGIN_RATE_LIMITED = AuthError("login_rate_limited", "Too many login attempts.", 429)
INVALID_USER_INPUT = AuthError("invalid_user_input", "User input was invalid.", 422)
USER_ALREADY_EXISTS = AuthError(
    "user_already_exists", "A user with this email already exists.", 409
)
