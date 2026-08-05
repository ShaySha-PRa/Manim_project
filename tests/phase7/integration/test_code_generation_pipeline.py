from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from manim_workbench_api.code_generation.dependencies import (
    get_code_generation_engine,
    get_code_generation_provider,
    get_code_generation_renderer,
)
from manim_workbench_api.code_generation.models import CandidateRenderResult
from manim_workbench_api.content_plans.models import ProviderResult
from manim_workbench_api.jobs.dependencies import get_internal_token
from manim_workbench_api.main import app
from sqlalchemy import Engine, create_engine, text

ROOT = Path(__file__).resolve().parents[3]
OWNER_ID = UUID("00000000-0000-0000-0000-000000000001")
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000002")
PROMPT_ID = UUID("00000000-0000-0000-0000-000000000003")
PLAN_ID = UUID("00000000-0000-0000-0000-000000000004")
VALID_SOURCE = (
    "from manim import Scene\n\n"
    "class GeneratedScene(Scene):\n"
    "    def construct(self):\n"
    "        self.wait(0.1)\n"
)


class StaticProvider:
    def __init__(self, source: str) -> None:
        self.source = source
        self.calls = 0

    def generate(self, messages):  # type: ignore[no-untyped-def]
        self.calls += 1
        return ProviderResult(
            content=json.dumps(
                {"scene_class": "GeneratedScene", "code": self.source, "assumptions": []}
            ),
            finish_reason="stop",
            request_id="phase7-test-request",
            model="deepseek-v4-flash",
        )


class AcceptingRenderer:
    def __init__(self) -> None:
        self.calls = 0

    def render(self, source_code: str, scene_class: str) -> CandidateRenderResult:
        self.calls += 1
        return CandidateRenderResult(succeeded=True)


def migrated_engine(tmp_path: Path) -> Engine:
    database_path = tmp_path / "phase7-integration.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    plan = {
        "schema_version": "1.1",
        "title": "一次函数",
        "audience": "high_school",
        "language": "zh-CN",
        "target_duration_seconds": 60,
        "derivation_style": "visual_intuition",
        "explicit_assumptions": [],
        "ambiguities": [],
        "scenes": [
            {
                "scene_number": 1,
                "teaching_goal": "观察斜率",
                "formula_steps": [{"expression": "y=kx", "explanation": "改变 k。"}],
                "visual_intent": "显示坐标轴。",
                "narration_placeholder": "比较斜率。",
            }
        ],
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, email, created_at) "
                "VALUES (:id, 'a@b.cn', '2026-08-05T00:00:00+00:00')"
            ),
            {"id": str(OWNER_ID)},
        )
        connection.execute(
            text(
                "INSERT INTO projects (id, owner_id, title, created_at) "
                "VALUES (:id, :owner, 'P7', '2026-08-05T00:00:00+00:00')"
            ),
            {"id": str(PROJECT_ID), "owner": str(OWNER_ID)},
        )
        connection.execute(
            text(
                "INSERT INTO prompt_versions "
                "(id, project_id, owner_id, version, parent_version_id, created_at, prompt) "
                "VALUES (:id, :project, :owner, 1, NULL, "
                "'2026-08-05T00:00:00+00:00', '一次函数')"
            ),
            {"id": str(PROMPT_ID), "project": str(PROJECT_ID), "owner": str(OWNER_ID)},
        )
        connection.execute(
            text(
                "INSERT INTO content_plan_versions "
                "(id, project_id, owner_id, version, parent_version_id, created_at, "
                "schema_version, content_json) VALUES "
                "(:id, :project, :owner, 1, NULL, "
                "'2026-08-05T00:00:00+00:00', '1.1', :content)"
            ),
            {
                "id": str(PLAN_ID),
                "project": str(PROJECT_ID),
                "owner": str(OWNER_ID),
                "content": json.dumps(plan, ensure_ascii=False),
            },
        )
    return engine


def request_json() -> dict[str, object]:
    return {
        "project_id": str(PROJECT_ID),
        "owner_id": str(OWNER_ID),
        "prompt_version_id": str(PROMPT_ID),
        "content_plan_version_id": str(PLAN_ID),
        "category": "function_visualization",
    }


def test_api_persists_only_a_sandbox_accepted_code_version(tmp_path: Path) -> None:
    engine = migrated_engine(tmp_path)
    provider = StaticProvider(VALID_SOURCE)
    renderer = AcceptingRenderer()
    app.dependency_overrides[get_code_generation_engine] = lambda: engine
    app.dependency_overrides[get_code_generation_provider] = lambda: provider
    app.dependency_overrides[get_code_generation_renderer] = lambda: renderer
    app.dependency_overrides[get_internal_token] = lambda: "phase7-token"
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/code-generations",
            headers={"X-Internal-Token": "phase7-token"},
            json=request_json(),
        )
        code_version_id = response.json().get("code_version", {}).get("id")
        read_response = client.get(
            f"/api/v1/code-versions/{code_version_id}",
            headers={"X-Internal-Token": "phase7-token"},
            params={"project_id": str(PROJECT_ID), "owner_id": str(OWNER_ID)},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "ready"
    assert read_response.status_code == 200
    assert read_response.json()["id"] == code_version_id
    assert provider.calls == renderer.calls == 1
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM code_versions")).scalar_one() == 1


def test_api_blocks_unsafe_source_before_renderer_and_hides_details(tmp_path: Path) -> None:
    engine = migrated_engine(tmp_path)
    provider = StaticProvider(
        "from manim import Scene\nclass GeneratedScene(Scene):\n"
        "    def construct(self):\n        open('/etc/passwd')\n"
    )
    renderer = AcceptingRenderer()
    app.dependency_overrides[get_code_generation_engine] = lambda: engine
    app.dependency_overrides[get_code_generation_provider] = lambda: provider
    app.dependency_overrides[get_code_generation_renderer] = lambda: renderer
    app.dependency_overrides[get_internal_token] = lambda: "phase7-token"
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/code-generations",
            headers={"X-Internal-Token": "phase7-token"},
            json=request_json(),
        )
    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "security_policy_violation",
            "message": "Generated source did not satisfy the security policy.",
        }
    }
    assert renderer.calls == 0
