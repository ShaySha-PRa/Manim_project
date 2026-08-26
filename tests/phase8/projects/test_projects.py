from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from manim_workbench_contracts import ContentPlanDraft
from sqlalchemy import Engine, create_engine, text

ROOT = Path(__file__).resolve().parents[3]
OWNER_A = UUID("00000000-0000-0000-0000-0000000000a1")
OWNER_B = UUID("00000000-0000-0000-0000-0000000000b2")


def _migrated_engine(tmp_path: Path) -> Engine:
    database_path = tmp_path / "projects.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0005_phase8")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        users = ((OWNER_A, "owner-a@example.test"), (OWNER_B, "owner-b@example.test"))
        for user_id, email in users:
            connection.execute(
                text("INSERT INTO users (id, email, created_at) VALUES (:id, :email, :created_at)"),
                {
                    "id": str(user_id),
                    "email": email,
                    "created_at": "2026-08-05T00:00:00+00:00",
                },
            )
    return engine


@pytest.fixture
def project_api(tmp_path: Path) -> tuple[TestClient, Engine]:
    from manim_workbench_api.projects.dependencies import (
        get_mutating_session_principal,
        get_project_engine,
        get_session_principal,
    )
    from manim_workbench_api.projects.router import router

    engine = _migrated_engine(tmp_path)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_project_engine] = lambda: engine
    app.dependency_overrides[get_session_principal] = lambda: SimpleNamespace(user_id=OWNER_A)
    app.dependency_overrides[get_mutating_session_principal] = lambda: SimpleNamespace(
        user_id=OWNER_A
    )
    return TestClient(app), engine


def _draft(title: str = "一次函数") -> dict[str, object]:
    return ContentPlanDraft(
        schema_version="1.1",
        title=title,
        audience="high_school",
        language="zh-CN",
        target_duration_seconds=60,
        derivation_style="step_by_step",
        explicit_assumptions=("学习者理解坐标系。",),
        ambiguities=(),
        scenes=(
            {
                "scene_number": 1,
                "teaching_goal": "理解斜率。",
                "formula_steps": ({"expression": "y=kx", "explanation": "斜率控制倾斜。"},),
                "visual_intent": "展示坐标轴和直线。",
                "narration_placeholder": "比较斜率。",
            },
        ),
    ).model_dump(mode="json")


def _create_project(client: TestClient, title: str = "项目") -> str:
    response = client.post("/api/v1/projects", json={"title": title})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_projects_crud_archive_and_cursor_pagination(
    project_api: tuple[TestClient, Engine],
) -> None:
    client, _engine = project_api
    project_ids = [_create_project(client, f"项目 {number}") for number in range(3)]

    first = client.get("/api/v1/projects", params={"limit": 2})
    assert first.status_code == 200
    assert len(first.json()["items"]) == 2
    assert first.json()["next_cursor"] is not None

    second = client.get(
        "/api/v1/projects", params={"limit": 2, "cursor": first.json()["next_cursor"]}
    )
    assert second.status_code == 200
    assert len(second.json()["items"]) == 1
    assert {item["id"] for item in first.json()["items"] + second.json()["items"]} == set(
        project_ids
    )

    updated = client.patch(
        f"/api/v1/projects/{project_ids[0]}", json={"title": "已更新", "archived": True}
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "已更新"
    assert updated.json()["archived_at"] is not None
    with _engine.connect() as connection:
        updated_at = connection.execute(
            text("SELECT updated_at FROM projects WHERE id = :id"), {"id": project_ids[0]}
        ).scalar_one()
    assert updated_at is not None

    restored = client.patch(f"/api/v1/projects/{project_ids[0]}", json={"archived": False})
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None


def test_project_routes_reject_owner_id_and_enforce_contract_input_limits(
    project_api: tuple[TestClient, Engine],
) -> None:
    client, _engine = project_api
    owner_in_body = client.post(
        "/api/v1/projects", json={"title": "项目", "owner_id": str(OWNER_B)}
    )
    overlong_title = client.post("/api/v1/projects", json={"title": "x" * 201})
    bad_limit = client.get("/api/v1/projects", params={"limit": 101})

    assert owner_in_body.status_code == 422
    assert overlong_title.status_code == 422
    assert bad_limit.status_code == 422
    for response in (owner_in_body, overlong_title, bad_limit):
        assert response.json()["error"]["code"] == "validation_error"


def test_project_routes_require_a_ready_session_principal(tmp_path: Path) -> None:
    from manim_workbench_api.auth.dependencies import (
        get_session_principal as get_authenticated_principal,
    )
    from manim_workbench_api.auth.models import SessionPrincipal
    from manim_workbench_api.projects.dependencies import get_project_engine
    from manim_workbench_api.projects.router import router

    engine = _migrated_engine(tmp_path)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_project_engine] = lambda: engine
    app.dependency_overrides[get_authenticated_principal] = lambda: SessionPrincipal(
        user_id=OWNER_A,
        email="owner-a@example.test",
        created_at=datetime.now(timezone.utc),
        must_change_password=True,
        session_id=uuid4(),
        expires_at=datetime.now(timezone.utc),
    )

    response = TestClient(app).get("/api/v1/projects")
    assert response.status_code == 403
    assert response.json() == {
        "error": {"code": "authorization_failed", "message": "Request was not authorized."}
    }


def test_project_routes_return_a_stable_error_when_session_is_missing() -> None:
    from manim_workbench_api.projects.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    response = TestClient(app).get("/api/v1/projects")

    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "authentication_failed", "message": "Authentication failed."}
    }


def test_cross_owner_project_and_versions_have_same_not_found_response(
    project_api: tuple[TestClient, Engine],
) -> None:
    client, _engine = project_api
    project_id = _create_project(client)
    prompt = client.post(
        f"/api/v1/projects/{project_id}/prompt-versions", json={"prompt": "解释一次函数的斜率。"}
    )
    assert prompt.status_code == 201

    from manim_workbench_api.projects.dependencies import (
        get_mutating_session_principal,
        get_session_principal,
    )

    client.app.dependency_overrides[get_session_principal] = lambda: SimpleNamespace(
        user_id=OWNER_B
    )
    client.app.dependency_overrides[get_mutating_session_principal] = lambda: SimpleNamespace(
        user_id=OWNER_B
    )
    cross_owner = client.get(f"/api/v1/projects/{project_id}")
    missing = client.get(f"/api/v1/projects/{uuid4()}")
    cross_owner_versions = client.get(f"/api/v1/projects/{project_id}/prompt-versions")
    cross_owner_content_plans = client.get(f"/api/v1/projects/{project_id}/content-plan-versions")

    assert (
        cross_owner.status_code
        == missing.status_code
        == cross_owner_versions.status_code
        == cross_owner_content_plans.status_code
        == 404
    )
    assert (
        cross_owner.json()
        == missing.json()
        == cross_owner_versions.json()
        == cross_owner_content_plans.json()
        == {"error": {"code": "project_not_found", "message": "Project was not found."}}
    )


def test_prompt_versions_append_with_a_valid_parent_chain(
    project_api: tuple[TestClient, Engine],
) -> None:
    client, engine = project_api
    project_id = _create_project(client)
    first = client.post(
        f"/api/v1/projects/{project_id}/prompt-versions", json={"prompt": "第一个提示词。"}
    )
    second = client.post(
        f"/api/v1/projects/{project_id}/prompt-versions", json={"prompt": "第二个提示词。"}
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["version"] == 1
    assert first.json()["parent_version_id"] is None
    assert second.json()["version"] == 2
    assert second.json()["parent_version_id"] == first.json()["id"]

    with engine.begin() as connection:
        with pytest.raises(Exception, match="append-only"):
            connection.execute(
                text("UPDATE prompt_versions SET prompt = '篡改' WHERE id = :id"),
                {"id": first.json()["id"]},
            )
        with pytest.raises(Exception, match="append-only"):
            connection.execute(
                text("DELETE FROM prompt_versions WHERE id = :id"), {"id": second.json()["id"]}
            )


def test_version_history_is_cursor_paginated(
    project_api: tuple[TestClient, Engine],
) -> None:
    client, engine = project_api
    project_id = _create_project(client)
    prompt_ids = []
    for number in range(3):
        response = client.post(
            f"/api/v1/projects/{project_id}/prompt-versions",
            json={"prompt": f"提示词 {number}"},
        )
        prompt_ids.append(response.json()["id"])

    first_prompts = client.get(
        f"/api/v1/projects/{project_id}/prompt-versions", params={"limit": 2}
    )
    assert first_prompts.status_code == 200
    assert [item["id"] for item in first_prompts.json()["items"]] == prompt_ids[:0:-1]
    assert first_prompts.json()["next_cursor"] == 2
    second_prompts = client.get(
        f"/api/v1/projects/{project_id}/prompt-versions",
        params={"limit": 2, "cursor": first_prompts.json()["next_cursor"]},
    )
    assert [item["id"] for item in second_prompts.json()["items"]] == prompt_ids[:1]
    assert second_prompts.json()["next_cursor"] is None

    plan_ids = [str(uuid4()) for _ in range(3)]
    with engine.begin() as connection:
        for version in range(1, 4):
            connection.execute(
                text(
                    "INSERT INTO content_plan_versions "
                    "(id, project_id, owner_id, version, parent_version_id, created_at, "
                    "schema_version, content_json) VALUES "
                    "(:id, :project_id, :owner_id, :version, :parent_version_id, "
                    ":created_at, '1.1', :content_json)"
                ),
                {
                    "id": plan_ids[version - 1],
                    "project_id": project_id,
                    "owner_id": str(OWNER_A),
                    "version": version,
                    "parent_version_id": None if version == 1 else plan_ids[version - 2],
                    "created_at": f"2026-08-05T00:00:0{version}+00:00",
                    "content_json": ContentPlanDraft.model_validate(_draft()).model_dump_json(),
                },
            )
    first_plans = client.get(
        f"/api/v1/projects/{project_id}/content-plan-versions", params={"limit": 2}
    )
    assert first_plans.status_code == 200
    assert [item["version"] for item in first_plans.json()["items"]] == [3, 2]
    assert first_plans.json()["next_cursor"] == 2


def test_content_plan_versions_require_the_current_parent_and_append_only(
    project_api: tuple[TestClient, Engine],
) -> None:
    client, engine = project_api
    project_id = _create_project(client)
    previous_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO content_plan_versions "
                "(id, project_id, owner_id, version, parent_version_id, created_at, "
                "schema_version, content_json) VALUES "
                "(:id, :project_id, :owner_id, 1, NULL, :created_at, '1.1', :content_json)"
            ),
            {
                "id": previous_id,
                "project_id": project_id,
                "owner_id": str(OWNER_A),
                "created_at": "2026-08-05T00:00:00+00:00",
                "content_json": ContentPlanDraft.model_validate(_draft()).model_dump_json(),
            },
        )

    stale_parent = client.post(
        f"/api/v1/projects/{project_id}/content-plan-versions",
        json={"parent_version_id": str(uuid4()), "content_plan": _draft()},
    )
    created = client.post(
        f"/api/v1/projects/{project_id}/content-plan-versions",
        json={"parent_version_id": previous_id, "content_plan": _draft("二次函数")},
    )

    assert stale_parent.status_code == 409
    assert stale_parent.json() == {
        "error": {"code": "version_conflict", "message": "Version parent is no longer current."}
    }
    assert created.status_code == 201
    assert created.json()["version"] == 2
    assert created.json()["parent_version_id"] == previous_id
    assert created.json()["schema_version"] == "1.1"

    stale_after_write = client.post(
        f"/api/v1/projects/{project_id}/content-plan-versions",
        json={"parent_version_id": previous_id, "content_plan": _draft("竞争写入")},
    )
    assert stale_after_write.status_code == 409
    assert stale_after_write.json() == stale_parent.json()

    with engine.begin() as connection:
        with pytest.raises(Exception, match="append-only"):
            connection.execute(
                text("DELETE FROM content_plan_versions WHERE id = :id"),
                {"id": created.json()["id"]},
            )


def test_content_plan_version_rejects_invalid_draft_and_large_prompt(
    project_api: tuple[TestClient, Engine],
) -> None:
    client, _engine = project_api
    project_id = _create_project(client)
    invalid_draft = client.post(
        f"/api/v1/projects/{project_id}/content-plan-versions",
        json={"parent_version_id": str(uuid4()), "content_plan": {"schema_version": "1.1"}},
    )
    overlong_prompt = client.post(
        f"/api/v1/projects/{project_id}/prompt-versions", json={"prompt": "x" * 20_001}
    )

    assert invalid_draft.status_code == 422
    assert overlong_prompt.status_code == 422
    assert invalid_draft.json()["error"]["code"] == "validation_error"
    assert overlong_prompt.json()["error"]["code"] == "validation_error"
