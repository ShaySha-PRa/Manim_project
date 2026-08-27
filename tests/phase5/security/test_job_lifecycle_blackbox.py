"""Independent HTTP-level race, recovery and information-boundary tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.workflows.migration_support import upgrade_workflow_database

TOKEN = "phase5-security-test-token"
HEADERS = {"X-Internal-Token": TOKEN}


class RecordingPublisher:
    def __init__(self) -> None:
        self.job_ids: list[UUID] = []

    def publish(self, job_id: UUID) -> None:
        self.job_ids.append(job_id)


@pytest.fixture
def api_client(
    tmp_path: Path,
) -> tuple[TestClient, Engine, RecordingPublisher]:
    from manim_workbench_api.database import create_database_engine
    from manim_workbench_api.jobs.dependencies import (
        get_database_engine,
        get_internal_token,
        get_job_signal_publisher,
    )
    from manim_workbench_api.main import app

    database_path = tmp_path / "phase5-blackbox.db"
    upgrade_workflow_database(database_path)
    engine = create_database_engine(f"sqlite:///{database_path}")
    _seed_submission_dependencies(engine)
    publisher = RecordingPublisher()
    app.dependency_overrides[get_database_engine] = lambda: engine
    app.dependency_overrides[get_job_signal_publisher] = lambda: publisher
    app.dependency_overrides[get_internal_token] = lambda: TOKEN
    client = TestClient(app)
    try:
        yield client, engine, publisher
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_main_application_exposes_protected_job_boundary(
    api_client: tuple[TestClient, Engine, RecordingPublisher],
) -> None:
    client, _engine, _publisher = api_client

    response = client.post("/api/v1/render-jobs", json=_submission("security-boundary-key"))

    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "INTERNAL_TOKEN_INVALID", "message": "internal token is invalid"}
    }


def test_concurrent_idempotent_submissions_create_one_job_and_one_signal(
    api_client: tuple[TestClient, Engine, RecordingPublisher],
) -> None:
    client, engine, publisher = api_client
    payload = _submission("concurrent-idempotency-key")

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(
            pool.map(
                lambda _: client.post("/api/v1/render-jobs", json=payload, headers=HEADERS),
                range(4),
            )
        )

    assert sorted(response.status_code for response in responses) == [200, 200, 200, 201]
    job_ids = {response.json()["id"] for response in responses}
    assert len(job_ids) == 1
    assert all("lease_token" not in response.json() for response in responses)
    with engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM render_jobs")).scalar_one()
    assert count == 1
    assert publisher.job_ids == [UUID(next(iter(job_ids)))]


def test_duplicate_signals_can_only_produce_one_concurrent_lease(
    api_client: tuple[TestClient, Engine, RecordingPublisher],
) -> None:
    client, engine, _publisher = api_client
    job_id = _submit(client, "concurrent-claim-key")

    def claim(runner_number: int):
        return client.post(
            f"/api/v1/internal/render-jobs/{job_id}/claim",
            json={"runner_id": f"runner-{runner_number}", "lease_seconds": 30},
            headers=HEADERS,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(claim, range(1, 5)))

    winners = [response for response in responses if response.status_code == 200]
    losers = [response for response in responses if response.status_code == 409]
    assert len(winners) == 1
    assert len(losers) == 3
    assert {response.json()["error"]["code"] for response in losers} == {"JOB_NOT_CLAIMABLE"}
    with engine.connect() as connection:
        attempt_count = connection.execute(
            text("SELECT attempt_count FROM render_jobs WHERE id = :id"), {"id": str(job_id)}
        ).scalar_one()
    assert attempt_count == 1


def test_api_restart_keeps_durable_job_state_readable(
    api_client: tuple[TestClient, Engine, RecordingPublisher],
) -> None:
    client, _engine, _publisher = api_client
    job_id = _submit(client, "api-restart-durability-key")

    restarted_client = TestClient(client.app)
    recovered = restarted_client.get(f"/api/v1/render-jobs/{job_id}", headers=HEADERS)

    assert recovered.status_code == 200
    assert recovered.json()["id"] == str(job_id)
    assert recovered.json()["status"] == "queued"


def test_expired_runner_token_cannot_mutate_a_reclaimed_job_after_runner_restart(
    api_client: tuple[TestClient, Engine, RecordingPublisher],
) -> None:
    client, engine, _publisher = api_client
    job_id = _submit(client, "expired-lease-recovery-key")
    old_token = _claim(client, job_id, "runner-old")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE render_jobs SET lease_expires_at = :expiry WHERE id = :id"),
            {"expiry": "2000-01-01T00:00:00+00:00", "id": str(job_id)},
        )

    restarted_client = TestClient(client.app)
    recoverable = restarted_client.get(
        "/api/v1/internal/render-jobs/recoverable?limit=10", headers=HEADERS
    )
    assert recoverable.status_code == 200
    assert str(job_id) in {item["id"] for item in recoverable.json()["jobs"]}

    new_token = _claim(restarted_client, job_id, "runner-new")
    stale_heartbeat = restarted_client.post(
        f"/api/v1/internal/render-jobs/{job_id}/heartbeat",
        json={"lease_token": old_token, "extend_seconds": 30},
        headers=HEADERS,
    )
    assert new_token != old_token
    assert stale_heartbeat.status_code == 409
    assert stale_heartbeat.json()["error"]["code"] == "LEASE_INVALID"


def test_cancel_complete_race_never_accepts_completion_after_cancel_request(
    api_client: tuple[TestClient, Engine, RecordingPublisher],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This Phase 5 test isolates the cancel/complete state-machine race. Phase 9
    # quality-gate behavior is covered with real metadata in its own integration tests.
    monkeypatch.setattr(
        "manim_workbench_api.jobs.router.legacy_quality_required",
        lambda _engine, _job_id: False,
    )
    client, _engine, _publisher = api_client
    job_id = _submit(client, "cancel-complete-race-key")
    lease_token = _claim(client, job_id, "runner-race")
    started = client.post(
        f"/api/v1/internal/render-jobs/{job_id}/start",
        json={"lease_token": lease_token, "extend_seconds": 30},
        headers=HEADERS,
    )
    assert started.status_code == 200

    with ThreadPoolExecutor(max_workers=2) as pool:
        cancellation, completion = pool.map(
            lambda action: _cancel_or_complete(client, action, job_id, lease_token),
            ("cancel", "complete"),
        )

    if cancellation.json().get("cancellation_requested_at") is not None:
        assert completion.status_code == 409
        assert completion.json()["error"]["code"] == "CANCELLATION_REQUESTED"
    else:
        assert completion.status_code == 200
        assert completion.json()["status"] == "succeeded"


def _cancel_or_complete(client: TestClient, action: str, job_id: UUID, lease_token: str):
    if action == "cancel":
        return client.post(f"/api/v1/render-jobs/{job_id}/cancel", headers=HEADERS)
    return client.post(
        f"/api/v1/internal/render-jobs/{job_id}/complete",
        json={"lease_token": lease_token, "artifacts": _artifacts()},
        headers=HEADERS,
    )


def _submission(idempotency_key: str) -> dict[str, str]:
    return {
        "project_id": "11111111-1111-1111-1111-111111111111",
        "owner_id": "22222222-2222-2222-2222-222222222222",
        "code_version_id": "33333333-3333-3333-3333-333333333333",
        "profile": "preview",
        "idempotency_key": idempotency_key,
    }


def _submit(client: TestClient, idempotency_key: str) -> UUID:
    response = client.post(
        "/api/v1/render-jobs", json=_submission(idempotency_key), headers=HEADERS
    )
    assert response.status_code == 201
    return UUID(response.json()["id"])


def _claim(client: TestClient, job_id: UUID, runner_id: str) -> str:
    response = client.post(
        f"/api/v1/internal/render-jobs/{job_id}/claim",
        json={"runner_id": runner_id, "lease_seconds": 30},
        headers=HEADERS,
    )
    assert response.status_code == 200
    return response.json()["lease_token"]


def _artifacts() -> list[dict[str, object]]:
    return [
        {
            "kind": kind,
            "relative_path": f"{kind}.bin",
            "sha256": "a" * 64,
            "byte_size": 1,
        }
        for kind in ("video", "thumbnail", "render_log", "metadata")
    ]


def _seed_submission_dependencies(engine: Engine) -> None:
    now = "2026-08-04T00:00:00+00:00"
    source = "from manim import Scene\nclass SceneUnderTest(Scene): pass\n"
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id, email, created_at) VALUES (:id, :email, :now)"),
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "email": "owner@example.com",
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO projects (id, owner_id, title, created_at) "
                "VALUES (:id, :owner_id, :title, :now)"
            ),
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "owner_id": "22222222-2222-2222-2222-222222222222",
                "title": "Security test project",
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO prompt_versions "
                "(id, project_id, owner_id, version, parent_version_id, created_at, prompt) "
                "VALUES (:id, :project_id, :owner_id, 1, NULL, :now, :prompt)"
            ),
            {
                "id": "44444444-4444-4444-4444-444444444444",
                "project_id": "11111111-1111-1111-1111-111111111111",
                "owner_id": "22222222-2222-2222-2222-222222222222",
                "now": now,
                "prompt": "test prompt",
            },
        )
        connection.execute(
            text(
                "INSERT INTO content_plan_versions "
                "(id, project_id, owner_id, version, parent_version_id, created_at, "
                "schema_version, content_json) "
                "VALUES (:id, :project_id, :owner_id, 1, NULL, :now, '1.0', '{}')"
            ),
            {
                "id": "55555555-5555-5555-5555-555555555555",
                "project_id": "11111111-1111-1111-1111-111111111111",
                "owner_id": "22222222-2222-2222-2222-222222222222",
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO code_versions "
                "(id, project_id, owner_id, version, parent_version_id, created_at, "
                "prompt_version_id, "
                "content_plan_version_id, source_code, source_sha256, scene_class, "
                "engine, engine_version) "
                "VALUES (:id, :project_id, :owner_id, 1, NULL, :now, :prompt_id, :plan_id, "
                ":source, :sha, :scene_class, 'manimce', '0.20.1')"
            ),
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "project_id": "11111111-1111-1111-1111-111111111111",
                "owner_id": "22222222-2222-2222-2222-222222222222",
                "now": now,
                "prompt_id": "44444444-4444-4444-4444-444444444444",
                "plan_id": "55555555-5555-5555-5555-555555555555",
                "source": source,
                "sha": sha256(source.encode("utf-8")).hexdigest(),
                "scene_class": "SceneUnderTest",
            },
        )
