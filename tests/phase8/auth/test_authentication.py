from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from argon2.low_level import Type
from fastapi import FastAPI
from fastapi.testclient import TestClient
from manim_workbench_api.auth.dependencies import get_auth_engine, get_auth_settings
from manim_workbench_api.auth.models import AuthSettings
from manim_workbench_api.auth.router import router
from manim_workbench_api.auth.service import AuthService
from sqlalchemy import Engine, create_engine, text

ROOT = Path(__file__).resolve().parents[3]
ORIGIN = "http://testserver"
PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "new-correct-horse-battery-staple"


@pytest.fixture
def auth_client(tmp_path: Path) -> tuple[TestClient, Engine]:
    database_path = tmp_path / "auth.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0005_phase8")
    engine = create_engine(f"sqlite:///{database_path}")
    service = AuthService(engine)
    service.create_user("teacher@example.test", PASSWORD)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_auth_engine] = lambda: engine
    app.dependency_overrides[get_auth_settings] = lambda: AuthSettings(
        allowed_origins=frozenset({ORIGIN}), cookie_secure=False
    )
    return TestClient(app, client=("127.0.0.1", 4567)), engine


def _login(client: TestClient, password: str = PASSWORD):
    return client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": "teacher@example.test", "password": password},
    )


def _csrf_headers(response) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


def test_password_hasher_is_explicit_argon2id(auth_client: tuple[TestClient, Engine]) -> None:
    _client, engine = auth_client

    with engine.connect() as connection:
        password_hash = connection.execute(
            text("SELECT password_hash FROM users WHERE email = :email"),
            {"email": "teacher@example.test"},
        ).scalar_one()

    assert PasswordHasher().type is Type.ID
    assert password_hash.startswith("$argon2id$")


def test_login_sets_only_safe_cookie_and_never_returns_password_or_session_token(
    auth_client: tuple[TestClient, Engine],
) -> None:
    client, engine = auth_client

    response = _login(client)

    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Max-Age=" in cookie
    assert "Secure" not in cookie
    assert response.headers["cache-control"] == "no-store"
    assert "password_hash" not in response.text
    assert "session_token" not in response.text
    with engine.connect() as connection:
        stored = (
            connection.execute(text("SELECT token_hash, csrf_token_hash FROM sessions"))
            .mappings()
            .one()
        )
    assert len(stored["token_hash"]) == len(stored["csrf_token_hash"]) == 64
    assert (
        stored["token_hash"]
        == sha256(response.cookies.get("manim_workbench_session").encode("utf-8")).hexdigest()
    )
    assert (
        stored["csrf_token_hash"]
        == sha256(response.json()["csrf_token"].encode("utf-8")).hexdigest()
    )


def test_secure_cookie_flag_is_enabled_only_by_explicit_setting(
    auth_client: tuple[TestClient, Engine],
) -> None:
    client, _engine = auth_client
    client.app.dependency_overrides[get_auth_settings] = lambda: AuthSettings(
        allowed_origins=frozenset({ORIGIN}), cookie_secure=True
    )

    response = _login(client)

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


def test_first_login_is_restricted_until_password_change(
    auth_client: tuple[TestClient, Engine],
) -> None:
    client, _engine = auth_client

    login = _login(client)
    session = client.get("/api/v1/auth/session")
    changed = client.post(
        "/api/v1/auth/change-password",
        headers=_csrf_headers(session),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert login.status_code == 200
    assert login.json()["user"]["must_change_password"] is True
    assert session.status_code == 200
    assert session.json()["user"]["must_change_password"] is True
    assert changed.status_code == 200
    assert changed.json()["user"]["must_change_password"] is False


def test_logout_and_password_change_revoke_old_sessions(
    auth_client: tuple[TestClient, Engine],
) -> None:
    client, _engine = auth_client
    first = _login(client)
    change = client.post(
        "/api/v1/auth/change-password",
        headers=_csrf_headers(first),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    old_cookie = first.cookies.get("manim_workbench_session")
    old_client = TestClient(client.app, client=("127.0.0.1", 4567))
    old_client.cookies.set("manim_workbench_session", old_cookie)
    old_session = old_client.get("/api/v1/auth/session")
    logout = client.post("/api/v1/auth/logout", headers=_csrf_headers(change))
    post_logout = client.get("/api/v1/auth/session")

    assert old_session.status_code == 401
    assert logout.status_code == 200
    assert post_logout.status_code == 401


def test_change_requests_require_allowed_origin_and_matching_csrf(
    auth_client: tuple[TestClient, Engine],
) -> None:
    client, _engine = auth_client
    login = _login(client)

    missing = client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN})
    cross_site = client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "https://attacker.example", "X-CSRF-Token": login.json()["csrf_token"]},
    )
    invalid = client.post(
        "/api/v1/auth/logout",
        headers={"Origin": ORIGIN, "X-CSRF-Token": "wrong"},
    )

    assert missing.status_code == cross_site.status_code == invalid.status_code == 403
    assert missing.json() == cross_site.json() == invalid.json()


def test_login_requires_origin_and_returns_generic_errors_for_unknown_disabled_and_bad_password(
    auth_client: tuple[TestClient, Engine],
) -> None:
    client, engine = auth_client
    without_origin = client.post(
        "/api/v1/auth/login",
        json={"email": "teacher@example.test", "password": PASSWORD},
    )
    unknown = client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": "unknown@example.test", "password": PASSWORD},
    )
    bad_password = _login(client, "incorrect-horse-battery-staple")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE users SET disabled_at = :now WHERE email = :email"),
            {"now": datetime.now(timezone.utc).isoformat(), "email": "teacher@example.test"},
        )
    disabled = _login(client)

    assert without_origin.status_code == 403
    assert unknown.status_code == bad_password.status_code == disabled.status_code == 401
    assert unknown.json() == bad_password.json() == disabled.json()


def test_persistent_login_rate_limit_survives_new_service_instance(
    auth_client: tuple[TestClient, Engine],
) -> None:
    client, engine = auth_client

    for _ in range(5):
        response = _login(client, "incorrect-horse-battery-staple")
        assert response.status_code == 401

    restarted_app = FastAPI()
    restarted_app.include_router(router, prefix="/api/v1")
    restarted_app.dependency_overrides[get_auth_engine] = lambda: engine
    restarted_app.dependency_overrides[get_auth_settings] = lambda: AuthSettings(
        allowed_origins=frozenset({ORIGIN}), cookie_secure=False
    )
    blocked = TestClient(restarted_app, client=("127.0.0.1", 4567)).post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": "teacher@example.test", "password": PASSWORD},
    )

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "login_rate_limited"
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM login_attempts")).scalar_one() == 5
        assert (
            connection.execute(
                text("SELECT identifier_hash, remote_addr_hash FROM login_attempts LIMIT 1")
            )
            .mappings()
            .one()["identifier_hash"]
            != "teacher@example.test"
        )


def test_session_survives_service_restart_but_rejects_expired_or_disabled_accounts(
    auth_client: tuple[TestClient, Engine],
) -> None:
    client, engine = auth_client
    login = _login(client)
    token = login.cookies.get("manim_workbench_session")
    restarted_app = FastAPI()
    restarted_app.include_router(router, prefix="/api/v1")
    restarted_app.dependency_overrides[get_auth_engine] = lambda: engine
    restarted_app.dependency_overrides[get_auth_settings] = lambda: AuthSettings(
        allowed_origins=frozenset({ORIGIN}), cookie_secure=False
    )
    restarted = TestClient(restarted_app, client=("127.0.0.1", 4567))
    restarted.cookies.set("manim_workbench_session", token)

    assert restarted.get("/api/v1/auth/session").status_code == 200
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE sessions SET expires_at = :expired"),
            {"expired": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()},
        )
    assert restarted.get("/api/v1/auth/session").status_code == 401
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE sessions SET expires_at = :future, revoked_at = NULL"),
            {"future": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
        )
        connection.execute(
            text("UPDATE users SET disabled_at = :now"),
            {"now": datetime.now(timezone.utc).isoformat()},
        )
    assert restarted.get("/api/v1/auth/session").status_code == 401
