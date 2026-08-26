from __future__ import annotations

from pathlib import Path
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from manim_workbench_api.auth.dependencies import get_auth_engine, get_auth_settings
from manim_workbench_api.auth.models import AuthSettings
from manim_workbench_api.auth.router import router as auth_router
from manim_workbench_api.auth.service import AuthService
from manim_workbench_api.projects.dependencies import get_project_engine
from manim_workbench_api.projects.router import router as projects_router
from manim_workbench_api.workflows.router import router as workflows_router
from manim_workbench_api.workflows.runtime import get_redis_workflow_task_notifier
from manim_workbench_api.workflows.service import WorkflowService
from manim_workbench_contracts import SceneBlockRunStatus, ScenePipeline
from sqlalchemy import Engine, create_engine, text

from tests.workflows.migration_support import upgrade_workflow_database

ORIGIN = "http://localhost:3000"


def _app(tmp_path: Path) -> tuple[FastAPI, Engine]:
    path = tmp_path / "workflow-api.db"
    upgrade_workflow_database(path)
    engine = create_engine(f"sqlite:///{path}")
    users = AuthService(engine)
    users.create_user("owner-a@example.test", "initial password 123")
    users.create_user("owner-b@example.test", "initial password 123")
    settings = AuthSettings(allowed_origins=frozenset({ORIGIN}), cookie_secure=False)
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(workflows_router, prefix="/api/v1")
    app.dependency_overrides[get_auth_engine] = lambda: engine
    app.dependency_overrides[get_project_engine] = lambda: engine
    app.dependency_overrides[get_auth_settings] = lambda: settings
    app.dependency_overrides[get_redis_workflow_task_notifier] = lambda: None
    return app, engine


def _ready_client(app: FastAPI, email: str) -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": email, "password": "initial password 123"},
    )
    changed = client.post(
        "/api/v1/auth/change-password",
        headers={"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]},
        json={
            "current_password": "initial password 123",
            "new_password": "replacement password 456",
        },
    )
    return client, {"Origin": ORIGIN, "X-CSRF-Token": changed.json()["csrf_token"]}


def _create_workflow(client: TestClient, headers: dict[str, str]):
    project = client.post(
        "/api/v1/projects", json={"title": "Workflow project"}, headers=headers
    )
    assert project.status_code == 201, project.text
    workflow = client.post(
        f"/api/v1/projects/{project.json()['id']}/video-workflows", headers=headers
    )
    assert workflow.status_code == 201, workflow.text
    scenes = []
    for title, prompt, mode in (
        ("Intro", "教学讲解这个公式。", "teaching"),
        ("Trajectory", "展示 Lorenz 轨迹。", "scientific"),
    ):
        response = client.post(
            f"/api/v1/video-workflows/{workflow.json()['id']}/scene-blocks",
            headers=headers,
            json={
                "title": title,
                "prompt": prompt,
                "pipeline_mode": mode,
                "target_duration_seconds": 30,
            },
        )
        assert response.status_code == 201, response.text
        scenes.append(response.json())
    node_ids = [str(uuid4()) for _ in range(4)]
    nodes = [
        {
            "id": node_ids[index],
            "kind": "scene",
            "scene_block_version_id": scenes[index]["version"]["id"],
        }
        for index in range(2)
    ] + [
        {"id": node_ids[2], "kind": "compose"},
        {"id": node_ids[3], "kind": "export"},
    ]
    version = client.post(
        f"/api/v1/video-workflows/{workflow.json()['id']}/versions",
        headers=headers,
        json={
            "global_brief": {
                "title": "Workflow",
                "language": "zh-CN",
                "target_duration_seconds": 60,
                "style_preset": "dark_scientific",
                "background": "#111111",
                "palette": ["#4488ff", "#ffcc22"],
            },
            "nodes": nodes,
            "edges": [
                {"source_node_id": node_ids[index], "target_node_id": node_ids[index + 1]}
                for index in range(3)
            ],
        },
    )
    assert version.status_code == 201, version.text
    return project.json(), workflow.json(), scenes, version.json()


def test_workflow_api_versions_async_submission_idempotency_and_owner_boundary(
    tmp_path: Path,
) -> None:
    app, engine = _app(tmp_path)
    owner_a, headers_a = _ready_client(app, "owner-a@example.test")
    project, workflow, scenes, version = _create_workflow(owner_a, headers_a)

    started = monotonic()
    first = owner_a.post(
        f"/api/v1/scene-block-versions/{scenes[0]['version']['id']}/runs",
        headers=headers_a,
        json={
            "workflow_version_id": version["id"],
            "profile": "preview",
            "idempotency_key": "scene-run-idempotency-0001",
        },
    )
    assert monotonic() - started < 1
    assert first.status_code == 202, first.text
    assert first.json()["status"] == "queued"
    duplicate = owner_a.post(
        f"/api/v1/scene-block-versions/{scenes[0]['version']['id']}/runs",
        headers=headers_a,
        json={
            "workflow_version_id": version["id"],
            "profile": "preview",
            "idempotency_key": "scene-run-idempotency-0001",
        },
    )
    assert duplicate.json()["id"] == first.json()["id"]

    workflow_service = WorkflowService(engine)
    planning = workflow_service.repository.append_scene_block_run_event(
        run_id=first.json()["id"],
        project_id=project["id"],
        owner_id=first.json()["owner_id"],
        expected_state_version=0,
        status=SceneBlockRunStatus.PLANNING,
        pipeline_used=ScenePipeline.TEACHING,
    )
    workflow_service.repository.append_scene_block_run_event(
        run_id=planning.id,
        project_id=planning.project_id,
        owner_id=planning.owner_id,
        expected_state_version=planning.state_version,
        status=SceneBlockRunStatus.FAILED,
        pipeline_used=ScenePipeline.TEACHING,
        error_code="render_failed",
    )
    initial_stream = owner_a.get(
        f"/api/v1/scene-block-runs/{first.json()['id']}/events",
        headers=headers_a,
    )
    assert "id: 0\nevent: scene_block_run\n" in initial_stream.text
    assert "id: 2\nevent: scene_block_run\n" in initial_stream.text
    replay = owner_a.get(
        f"/api/v1/scene-block-runs/{first.json()['id']}/events",
        headers={**headers_a, "Last-Event-ID": "0"},
    )
    assert replay.status_code == 200
    assert replay.headers["content-type"].startswith("text/event-stream")
    assert "id: 0\n" not in replay.text
    assert "id: 1\nevent: scene_block_run\n" in replay.text
    assert "id: 2\nevent: scene_block_run\n" in replay.text
    assert '"status":"failed"' in replay.text
    terminal_reconnect = owner_a.get(
        f"/api/v1/scene-block-runs/{first.json()['id']}/events",
        headers={**headers_a, "Last-Event-ID": "2"},
    )
    assert terminal_reconnect.text == "retry: 1000\n\n"
    polled = owner_a.get(f"/api/v1/scene-block-runs/{first.json()['id']}")
    assert polled.status_code == 200
    assert polled.json()["state_version"] == 2
    assert polled.json()["status"] == "failed"

    composition = owner_a.post(
        f"/api/v1/workflow-versions/{version['id']}/composition-runs",
        headers=headers_a,
        json={"profile": "preview", "idempotency_key": "0" * 32},
    )
    assert composition.status_code == 202
    assert composition.json()["status"] == "not_ready_to_compose"
    assert composition.json()["error_code"] == "scene_clips_not_ready"
    composition_replay = owner_a.get(
        f"/api/v1/composition-runs/{composition.json()['id']}/events",
        headers={**headers_a, "Last-Event-ID": "0"},
    )
    assert composition_replay.status_code == 200
    assert "id: 1\nevent: composition_run\n" in composition_replay.text
    assert '"status":"not_ready_to_compose"' in composition_replay.text
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM workflow_tasks")).scalar_one() == 1

    owner_b, _headers_b = _ready_client(app, "owner-b@example.test")
    for path in (
        f"/api/v1/video-workflows/{workflow['id']}",
        f"/api/v1/workflow-versions/{version['id']}",
        f"/api/v1/scene-block-runs/{first.json()['id']}",
        f"/api/v1/scene-block-runs/{first.json()['id']}/events",
        f"/api/v1/composition-runs/{composition.json()['id']}",
        f"/api/v1/composition-runs/{composition.json()['id']}/events",
    ):
        response = owner_b.get(path)
        assert response.status_code == 404
        assert "sha256" not in response.text
        assert project["id"] not in response.text


def test_workflow_mutations_require_existing_csrf_boundary_and_openapi_lists_routes(
    tmp_path: Path,
) -> None:
    app, _engine = _app(tmp_path)
    client, headers = _ready_client(app, "owner-a@example.test")
    project = client.post(
        "/api/v1/projects", json={"title": "CSRF project"}, headers=headers
    ).json()
    missing = client.post(f"/api/v1/projects/{project['id']}/video-workflows")
    assert missing.status_code == 403
    allowed = client.post(
        f"/api/v1/projects/{project['id']}/video-workflows", headers=headers
    )
    assert allowed.status_code == 201
    paths = app.openapi()["paths"]
    assert "/api/v1/video-workflows/{workflow_id}/versions" in paths
    assert "/api/v1/scene-block-versions/{version_id}/runs" in paths
    assert "/api/v1/scene-block-runs/{run_id}/events" in paths
    assert "/api/v1/workflow-versions/{version_id}/composition-runs" in paths
    assert "/api/v1/composition-runs/{run_id}/events" in paths
    assert "/api/v1/composition-runs/{run_id}/artifact" in paths
