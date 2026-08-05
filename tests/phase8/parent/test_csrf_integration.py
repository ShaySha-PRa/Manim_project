from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from manim_workbench_api.auth.dependencies import get_auth_engine, get_auth_settings
from manim_workbench_api.auth.models import AuthSettings
from manim_workbench_api.auth.router import router as auth_router
from manim_workbench_api.auth.service import AuthService
from manim_workbench_api.projects.dependencies import get_project_engine
from manim_workbench_api.projects.router import router as projects_router
from sqlalchemy import Engine, create_engine

ROOT = Path(__file__).resolve().parents[3]
ORIGIN = "http://localhost:3000"


def _app(tmp_path: Path) -> tuple[TestClient, Engine]:
    path = tmp_path / "csrf.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{path}")
    AuthService(engine).create_user("teacher@example.test", "initial password 123")
    settings = AuthSettings(allowed_origins=frozenset({ORIGIN}), cookie_secure=False)
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(projects_router, prefix="/api/v1")
    app.dependency_overrides[get_auth_engine] = lambda: engine
    app.dependency_overrides[get_project_engine] = lambda: engine
    app.dependency_overrides[get_auth_settings] = lambda: settings
    return TestClient(app), engine


def test_project_mutations_require_session_bound_csrf_and_origin(tmp_path: Path) -> None:
    client, _engine = _app(tmp_path)
    login = client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": "teacher@example.test", "password": "initial password 123"},
    )
    csrf = login.json()["csrf_token"]
    changed = client.post(
        "/api/v1/auth/change-password",
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        json={
            "current_password": "initial password 123",
            "new_password": "replacement password 456",
        },
    )
    csrf = changed.json()["csrf_token"]

    missing = client.post("/api/v1/projects", headers={"Origin": ORIGIN}, json={"title": "A"})
    wrong = client.post(
        "/api/v1/projects",
        headers={"Origin": ORIGIN, "X-CSRF-Token": "wrong" * 10},
        json={"title": "B"},
    )
    allowed = client.post(
        "/api/v1/projects",
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        json={"title": "C"},
    )

    assert missing.status_code == wrong.status_code == 403
    assert allowed.status_code == 201
