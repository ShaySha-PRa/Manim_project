from __future__ import annotations

from pathlib import Path

from manim_workbench_api.workflows.director.repository import DirectorRepository
from manim_workbench_api.workflows.director.service import DirectorPlanningService
from sqlalchemy import text

from tests.workflows.test_api import _app, _ready_client
from tests.workflows.test_director_service import FakeProvider, _candidate


def test_director_http_is_async_csrf_scoped_and_apply_has_no_execution_side_effect(
    tmp_path: Path,
) -> None:
    app, engine = _app(tmp_path)
    owner_a, headers_a = _ready_client(app, "owner-a@example.test")
    project = owner_a.post(
        "/api/v1/projects", headers=headers_a, json={"title": "Director project"}
    ).json()
    payload = {
        "objective": "Create a bounded explanation with verified evidence.",
        "language": "zh-CN",
        "target_duration_seconds": 60,
        "style_preset": "dark_scientific",
        "asset_version_ids": [],
        "idempotency_key": "director-http-request-0001",
    }
    denied = owner_a.post(
        f"/api/v1/projects/{project['id']}/director-plans", json=payload
    )
    assert denied.status_code == 403
    created = owner_a.post(
        f"/api/v1/projects/{project['id']}/director-plans",
        headers=headers_a,
        json=payload,
    )
    assert created.status_code == 202, created.text
    assert created.json()["status"] == "queued"
    plan_id = created.json()["id"]
    fetched = owner_a.get(
        f"/api/v1/projects/{project['id']}/director-plans/{plan_id}"
    )
    assert fetched.status_code == 200
    replay = owner_a.post(
        f"/api/v1/projects/{project['id']}/director-plans",
        headers=headers_a,
        json=payload,
    )
    assert replay.json()["id"] == plan_id

    owner_b, _headers_b = _ready_client(app, "owner-b@example.test")
    hidden = owner_b.get(
        f"/api/v1/projects/{project['id']}/director-plans/{plan_id}"
    )
    assert hidden.status_code == 404
    assert plan_id not in hidden.text

    provider = FakeProvider(_candidate())
    ready = DirectorPlanningService(DirectorRepository(engine), provider).execute(
        plan_id, project["id"], created.json()["owner_id"]
    )
    assert ready.draft is not None
    applied = owner_a.post(
        f"/api/v1/projects/{project['id']}/director-plans/{plan_id}/apply",
        headers=headers_a,
        json={
            "draft": ready.draft.model_dump(mode="json"),
            "scene_asset_version_ids": [[], []],
            "idempotency_key": "director-apply-request-0001",
        },
    )
    assert applied.status_code == 201, applied.text
    assert len([node for node in applied.json()["nodes"] if node["kind"] == "scene"]) == 2
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM video_workflow_versions")
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT COUNT(*) FROM scene_block_versions")
        ).scalar_one() == 2
        assert connection.execute(text("SELECT COUNT(*) FROM scene_block_runs")).scalar_one() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM render_jobs")).scalar_one() == 0
        assert connection.execute(
            text("SELECT COUNT(*) FROM workflow_composition_runs")
        ).scalar_one() == 0


def test_director_apply_rejects_nonready_and_invalid_project_without_partial_rows(
    tmp_path: Path,
) -> None:
    app, engine = _app(tmp_path)
    client, headers = _ready_client(app, "owner-a@example.test")
    project = client.post(
        "/api/v1/projects", headers=headers, json={"title": "Director project"}
    ).json()
    created = client.post(
        f"/api/v1/projects/{project['id']}/director-plans",
        headers=headers,
        json={
            "objective": "Create a bounded explanation.",
            "language": "zh-CN",
            "target_duration_seconds": 60,
            "idempotency_key": "director-nonready-request-0001",
        },
    )
    assert created.status_code == 202
    rejected = client.post(
        f"/api/v1/projects/{project['id']}/director-plans/{created.json()['id']}/apply",
        headers=headers,
        json={
            "draft": _candidate(),
            "scene_asset_version_ids": [[], []],
            "idempotency_key": "director-nonready-apply-0001",
        },
    )
    assert rejected.status_code in {409, 422}
    missing = client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000099/director-plans",
        headers=headers,
        json={
            "objective": "Create a bounded explanation.",
            "language": "zh-CN",
            "target_duration_seconds": 60,
            "idempotency_key": "director-missing-project-0001",
        },
    )
    assert missing.status_code == 404
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM video_workflows")).scalar_one() == 0
