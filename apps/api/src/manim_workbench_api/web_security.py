from __future__ import annotations

import os
from collections.abc import Iterable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response

DEFAULT_ORIGIN = "http://localhost:3000"


def configured_origins() -> tuple[str, ...]:
    raw = os.environ.get("MANIM_WORKBENCH_ALLOWED_ORIGINS", DEFAULT_ORIGIN)
    return validate_origins(part.strip() for part in raw.split(",") if part.strip())


def validate_origins(origins: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            origin == "*"
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError("MANIM_WORKBENCH_ALLOWED_ORIGINS contains an invalid origin")
        normalized.append(origin.rstrip("/"))
    if not normalized:
        raise RuntimeError("MANIM_WORKBENCH_ALLOWED_ORIGINS must not be empty")
    return tuple(dict.fromkeys(normalized))


def configure_web_security(
    app: FastAPI,
    *,
    allowed_origins: tuple[str, ...] | None = None,
    secure: bool | None = None,
) -> None:
    origins = validate_origins(allowed_origins or configured_origins())
    secure_mode = (
        os.environ.get("MANIM_WORKBENCH_COOKIE_SECURE", "false").lower() == "true"
        if secure is None
        else secure
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Last-Event-ID", "X-CSRF-Token"],
        max_age=600,
    )

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'; object-src 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if secure_mode:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response
