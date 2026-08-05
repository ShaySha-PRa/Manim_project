from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from manim_workbench_api.content_plans.dependencies import (
    get_content_plan_engine,
    get_content_plan_provider,
)
from manim_workbench_api.content_plans.models import ProviderResult, ProviderUsage
from manim_workbench_api.jobs.dependencies import get_internal_token
from manim_workbench_api.main import app
from sqlalchemy import Engine, create_engine, text

ROOT = Path(__file__).resolve().parents[3]
OWNER_ID = UUID("00000000-0000-0000-0000-000000000001")
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000002")
PROMPT_ID = UUID("00000000-0000-0000-0000-000000000003")


class SequenceProvider:
    def __init__(self, contents: list[str]) -> None:
        self._contents = iter(contents)
        self.calls = 0

    def generate(self, messages):  # type: ignore[no-untyped-def]
        assert len(messages) == 2
        self.calls += 1
        return ProviderResult(
            content=next(self._contents),
            finish_reason="stop",
            request_id=f"request-{self.calls}",
            model="deepseek-v4-flash",
            usage=ProviderUsage(prompt_tokens=100, completion_tokens=200),
        )


def ready_json() -> str:
    return json.dumps(
        {
            "outcome": "ready",
            "plan": {
                "schema_version": "1.1",
                "title": "一次函数图像",
                "audience": "high_school",
                "language": "zh-CN",
                "target_duration_seconds": 60,
                "derivation_style": "visual_intuition",
                "explicit_assumptions": ["学习者理解坐标系。"],
                "ambiguities": [],
                "scenes": [
                    {
                        "scene_number": 1,
                        "teaching_goal": "理解斜率与函数图像的关系。",
                        "formula_steps": [
                            {"expression": "y=kx", "explanation": "固定截距为零。"}
                        ],
                        "visual_intent": "显示坐标轴、定义域和 k 正负时的关键单调行为。",
                        "narration_placeholder": "比较斜率变化。",
                    }
                ],
            },
            "clarifications": [],
            "limitations": [],
        },
        ensure_ascii=False,
    )


def migrated_engine(tmp_path: Path) -> Engine:
    database_path = tmp_path / "phase6-integration.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id, email, created_at) VALUES (:id, :email, :created_at)"),
            {
                "id": str(OWNER_ID),
                "email": "phase6@example.com",
                "created_at": "2026-08-04T00:00:00+00:00",
            },
        )
        connection.execute(
            text(
                "INSERT INTO projects (id, owner_id, title, created_at) "
                "VALUES (:id, :owner_id, :title, :created_at)"
            ),
            {
                "id": str(PROJECT_ID),
                "owner_id": str(OWNER_ID),
                "title": "Phase 6",
                "created_at": "2026-08-04T00:00:00+00:00",
            },
        )
        connection.execute(
            text(
                "INSERT INTO prompt_versions "
                "(id, project_id, owner_id, version, parent_version_id, created_at, prompt) "
                "VALUES (:id, :project_id, :owner_id, 1, NULL, :created_at, :prompt)"
            ),
            {
                "id": str(PROMPT_ID),
                "project_id": str(PROJECT_ID),
                "owner_id": str(OWNER_ID),
                "created_at": "2026-08-04T00:00:00+00:00",
                "prompt": "请展示一次函数图像如何随斜率变化。",
            },
        )
    return engine


def request_json() -> dict[str, object]:
    return {
        "project_id": str(PROJECT_ID),
        "owner_id": str(OWNER_ID),
        "prompt_version_id": str(PROMPT_ID),
        "audience": "high_school",
        "language": "zh-CN",
        "target_duration_seconds": 60,
        "derivation_style": "visual_intuition",
        "explicit_assumptions": ["学习者理解坐标系。"],
    }


def client_for(engine: Engine, provider: SequenceProvider) -> TestClient:
    app.dependency_overrides[get_content_plan_engine] = lambda: engine
    app.dependency_overrides[get_content_plan_provider] = lambda: provider
    app.dependency_overrides[get_internal_token] = lambda: "phase6-test-token"
    return TestClient(app)


def test_ready_plan_is_persisted_with_redacted_attempt_metadata(tmp_path: Path) -> None:
    engine = migrated_engine(tmp_path)
    provider = SequenceProvider([ready_json()])
    with client_for(engine, provider) as client:
        response = client.post(
            "/api/v1/content-plans/generate",
            headers={"X-Internal-Token": "phase6-test-token"},
            json=request_json(),
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "ready"
    assert body["content_plan_version"]["schema_version"] == "1.1"
    with engine.connect() as connection:
        count = connection.execute(
            text("SELECT COUNT(*) FROM content_plan_versions")
        ).scalar_one()
        assert count == 1
        attempt = connection.execute(
            text(
                "SELECT provider_request_id, provider_model, prompt_tokens, completion_tokens "
                "FROM generation_attempts"
            )
        ).one()
    assert tuple(attempt) == ("request-1", "deepseek-v4-flash", 100, 200)


def test_invalid_json_retries_exactly_once_then_persists(tmp_path: Path) -> None:
    engine = migrated_engine(tmp_path)
    provider = SequenceProvider(["{invalid", ready_json()])
    with client_for(engine, provider) as client:
        response = client.post(
            "/api/v1/content-plans/generate",
            headers={"X-Internal-Token": "phase6-test-token"},
            json=request_json(),
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["attempts_used"] == 2
    assert provider.calls == 2
    with engine.connect() as connection:
        attempts = connection.execute(
            text(
                "SELECT attempt_number, status, error_code "
                "FROM generation_attempts ORDER BY attempt_number"
            )
        ).all()
    assert attempts == [
        (1, "failed", "provider_invalid_json"),
        (2, "succeeded", None),
    ]


def test_owner_mismatch_is_hidden_as_not_found_and_never_calls_provider(tmp_path: Path) -> None:
    engine = migrated_engine(tmp_path)
    provider = SequenceProvider([ready_json()])
    body = request_json()
    body["owner_id"] = "00000000-0000-0000-0000-000000000099"
    with client_for(engine, provider) as client:
        response = client.post(
            "/api/v1/content-plans/generate",
            headers={"X-Internal-Token": "phase6-test-token"},
            json=body,
        )
    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "prompt_version_not_found",
            "message": "Prompt version was not found.",
        }
    }
    assert provider.calls == 0
