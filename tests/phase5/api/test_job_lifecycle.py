from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from manim_workbench_contracts import RenderProfile
from sqlalchemy import Engine, text


class RecordingPublisher:
    def __init__(self) -> None:
        self.job_ids: list[UUID] = []

    def publish(self, job_id: UUID) -> None:
        self.job_ids.append(job_id)


@pytest.fixture
def api_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, Engine, RecordingPublisher]:
    from manim_workbench_api.database import create_database_engine
    from manim_workbench_api.jobs.dependencies import (
        get_database_engine,
        get_internal_token,
        get_job_signal_publisher,
    )
    from manim_workbench_api.jobs.router import router

    engine = create_database_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    _create_schema(engine)
    publisher = RecordingPublisher()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_database_engine] = lambda: engine
    app.dependency_overrides[get_job_signal_publisher] = lambda: publisher
    app.dependency_overrides[get_internal_token] = lambda: "phase5-test-token"
    monkeypatch.delenv("MANIM_WORKBENCH_INTERNAL_TOKEN", raising=False)
    return TestClient(app), engine, publisher


def test_submit_is_idempotent_and_signals_only_once(
    api_client: tuple[TestClient, Engine, RecordingPublisher],
) -> None:
    client, _engine, publisher = api_client
    payload = _submission_payload()

    first = client.post("/api/v1/render-jobs", json=payload, headers=_token_headers())
    second = client.post("/api/v1/render-jobs", json=payload, headers=_token_headers())

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert first.json()["status"] == "queued"
    assert len(publisher.job_ids) == 1
    assert publisher.job_ids[0] == UUID(first.json()["id"])


def test_claim_is_single_winner_and_old_lease_cannot_mutate(
    api_client: tuple[TestClient, Engine, RecordingPublisher],
) -> None:
    client, _engine, _publisher = api_client
    job_id = _submit(client)

    claim = client.post(
        f"/api/v1/internal/render-jobs/{job_id}/claim",
        json={"runner_id": "runner-a", "lease_seconds": 30},
        headers=_token_headers(),
    )
    duplicate = client.post(
        f"/api/v1/internal/render-jobs/{job_id}/claim",
        json={"runner_id": "runner-b", "lease_seconds": 30},
        headers=_token_headers(),
    )

    assert claim.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "JOB_NOT_CLAIMABLE"

    old_token = "0" * 64
    heartbeat = client.post(
        f"/api/v1/internal/render-jobs/{job_id}/heartbeat",
        json={"lease_token": old_token, "extend_seconds": 30},
        headers=_token_headers(),
    )
    assert heartbeat.status_code == 409
    assert heartbeat.json()["error"]["code"] == "LEASE_INVALID"


def test_cancel_request_blocks_success_and_is_idempotent(
    api_client: tuple[TestClient, Engine, RecordingPublisher],
) -> None:
    client, _engine, _publisher = api_client
    job_id = _submit(client)
    lease_token = _claim_and_start(client, job_id)

    cancelled = client.post(f"/api/v1/render-jobs/{job_id}/cancel", headers=_token_headers())
    duplicate = client.post(f"/api/v1/render-jobs/{job_id}/cancel", headers=_token_headers())
    completion = client.post(
        f"/api/v1/internal/render-jobs/{job_id}/complete",
        json={"lease_token": lease_token, "artifacts": _artifacts()},
        headers=_token_headers(),
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "running"
    assert cancelled.json()["cancellation_requested_at"] is not None
    assert duplicate.status_code == 200
    assert completion.status_code == 409
    assert completion.json()["error"]["code"] == "CANCELLATION_REQUESTED"


def test_complete_requires_each_artifact_kind_and_publishes_atomically(
    api_client: tuple[TestClient, Engine, RecordingPublisher],
) -> None:
    client, engine, _publisher = api_client
    job_id = _submit(client)
    lease_token = _claim_and_start(client, job_id)
    invalid = client.post(
        f"/api/v1/internal/render-jobs/{job_id}/complete",
        json={"lease_token": lease_token, "artifacts": _artifacts(kind_override="video")},
        headers=_token_headers(),
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "ARTIFACT_SET_INVALID"

    valid = client.post(
        f"/api/v1/internal/render-jobs/{job_id}/complete",
        json={"lease_token": lease_token, "artifacts": _artifacts()},
        headers=_token_headers(),
    )
    assert valid.status_code == 200
    assert valid.json()["status"] == "succeeded"
    with engine.connect() as connection:
        artifact_count = connection.execute(
            text("SELECT COUNT(*) FROM artifacts WHERE render_job_id = :job_id"),
            {"job_id": str(job_id)},
        ).scalar_one()
    assert artifact_count == 4


def test_internal_routes_require_constant_time_environment_token(
    api_client: tuple[TestClient, Engine, RecordingPublisher],
) -> None:
    client, _engine, _publisher = api_client
    response = client.post(
        f"/api/v1/internal/render-jobs/{uuid4()}/claim",
        json={"runner_id": "runner-a", "lease_seconds": 30},
    )
    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "INTERNAL_TOKEN_INVALID", "message": "internal token is invalid"}
    }


def test_invalid_contract_body_uses_stable_machine_error(
    api_client: tuple[TestClient, Engine, RecordingPublisher],
) -> None:
    client, _engine, _publisher = api_client

    response = client.post(
        "/api/v1/render-jobs",
        json={"idempotency_key": "too-short"},
        headers=_token_headers(),
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "VALIDATION_ERROR", "message": "request payload is invalid"}
    }


def _submission_payload() -> dict[str, str]:
    return {
        "project_id": "11111111-1111-1111-1111-111111111111",
        "owner_id": "22222222-2222-2222-2222-222222222222",
        "code_version_id": "33333333-3333-3333-3333-333333333333",
        "profile": RenderProfile.PREVIEW.value,
        "idempotency_key": "idem-key-for-phase-five",
    }


def _token_headers() -> dict[str, str]:
    return {"X-Internal-Token": "phase5-test-token"}


def _submit(client: TestClient) -> UUID:
    response = client.post(
        "/api/v1/render-jobs", json=_submission_payload(), headers=_token_headers()
    )
    assert response.status_code == 201
    return UUID(response.json()["id"])


def _claim_and_start(client: TestClient, job_id: UUID) -> str:
    claim = client.post(
        f"/api/v1/internal/render-jobs/{job_id}/claim",
        json={"runner_id": "runner-a", "lease_seconds": 30},
        headers=_token_headers(),
    )
    assert claim.status_code == 200
    lease_token = claim.json()["lease_token"]
    started = client.post(
        f"/api/v1/internal/render-jobs/{job_id}/start",
        json={"lease_token": lease_token, "extend_seconds": 30},
        headers=_token_headers(),
    )
    assert started.status_code == 200
    return lease_token


def _artifacts(kind_override: str | None = None) -> list[dict[str, object]]:
    kinds = ["video", "thumbnail", "render_log", "metadata"]
    if kind_override is not None:
        kinds[-1] = kind_override
    return [
        {
            "kind": kind,
            "relative_path": f"{kind}.bin",
            "sha256": "a" * 64,
            "byte_size": 42,
        }
        for kind in kinds
    ]


def _create_schema(engine: Engine) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE render_jobs (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                    code_version_id TEXT NOT NULL, profile TEXT NOT NULL, status TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
                    started_at TEXT, finished_at TEXT, failure_code TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0, lease_owner TEXT,
                    lease_token TEXT, lease_expires_at TEXT, heartbeat_at TEXT,
                    cancellation_requested_at TEXT, state_version INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE artifacts (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                    render_job_id TEXT NOT NULL, kind TEXT NOT NULL, relative_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL, byte_size INTEGER NOT NULL, created_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text("SELECT :now"), {"now": now}
        )
