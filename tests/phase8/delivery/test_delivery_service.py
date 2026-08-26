from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from manim_workbench_api.auth.dependencies import get_session_principal
from manim_workbench_api.auth.models import SessionPrincipal
from manim_workbench_api.delivery.dependencies import get_artifact_root, get_delivery_service
from manim_workbench_api.delivery.router import router
from manim_workbench_api.delivery.service import (
    DeliveryNotFound,
    DeliveryService,
    EventCursor,
)
from manim_workbench_contracts import PipelineStage, RenderJobStatus
from manim_workbench_contracts.models import ArtifactKind
from sqlalchemy import Engine, create_engine, text

from tests.workflows.migration_support import upgrade_workflow_database

OWNER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_OWNER_ID = UUID("00000000-0000-0000-0000-000000000009")
JOB_ID = UUID("00000000-0000-0000-0000-000000000010")
ARTIFACT_ID = UUID("00000000-0000-0000-0000-000000000020")


@dataclass(frozen=True)
class Principal:
    user_id: UUID


def session_principal(user_id: UUID) -> SessionPrincipal:
    now = datetime.now(timezone.utc)
    return SessionPrincipal(
        user_id=user_id,
        email="owner@example.test",
        created_at=now,
        must_change_password=False,
        session_id=UUID("00000000-0000-0000-0000-000000000030"),
        expires_at=now,
    )


def migrated_engine(tmp_path: Path) -> Engine:
    database_path = tmp_path / "delivery.db"
    upgrade_workflow_database(database_path)
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        users = (
            (OWNER_ID, "owner@example.test"),
            (OTHER_OWNER_ID, "other@example.test"),
        )
        for user_id, email in users:
            connection.execute(
                text("INSERT INTO users (id, email, created_at) VALUES (:id, :email, :created_at)"),
                {"id": str(user_id), "email": email, "created_at": "2026-08-05T00:00:00+00:00"},
            )
        connection.execute(
            text(
                "INSERT INTO render_jobs ("
                "id, project_id, owner_id, code_version_id, profile, status, idempotency_key, "
                "created_at, attempt_count, state_version) VALUES ("
                ":id, :project_id, :owner_id, :code_version_id, 'preview', 'queued', "
                ":idempotency_key, :created_at, 1, 0)"
            ),
            {
                "id": str(JOB_ID),
                "project_id": "00000000-0000-0000-0000-000000000002",
                "owner_id": str(OWNER_ID),
                "code_version_id": "00000000-0000-0000-0000-000000000003",
                "idempotency_key": "delivery-test-idempotency-key",
                "created_at": "2026-08-05T00:00:00+00:00",
            },
        )
        connection.execute(
            text(
                "INSERT INTO job_events (render_job_id, owner_id, state_version, stage, status, "
                "error_code, created_at) VALUES "
                "(:job_id, :owner_id, 1, 'preview_render', 'running', NULL, :created_at)"
            ),
            {
                "job_id": str(JOB_ID),
                "owner_id": str(OWNER_ID),
                "created_at": "2026-08-05T00:00:00+00:00",
            },
        )
        connection.execute(
            text("UPDATE render_jobs SET status = 'succeeded', state_version = 2 WHERE id = :id"),
            {"id": str(JOB_ID)},
        )
    return engine


def service(tmp_path: Path) -> DeliveryService:
    return DeliveryService(migrated_engine(tmp_path), tmp_path / "artifacts")


def test_default_artifact_root_matches_the_runner_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MANIM_WORKBENCH_ARTIFACT_ROOT", raising=False)

    assert get_artifact_root() == Path("runtime/phase5/artifacts")


def test_cursor_accepts_only_bounded_non_negative_decimal_values() -> None:
    assert EventCursor.parse(None).value == 0
    assert EventCursor.parse("0").value == 0
    assert EventCursor.parse("123").value == 123
    for invalid in ("-1", "+1", " 1", "1.0", "abc", "1000001"):
        with pytest.raises(ValueError):
            EventCursor.parse(invalid)


def test_event_replay_uses_durable_event_ids_and_excludes_prior_cursor(tmp_path: Path) -> None:
    events = service(tmp_path).events(Principal(OWNER_ID), JOB_ID, EventCursor.parse("1"))

    assert [event.event_id for event in events] == [2, 3]
    assert events[-1].status is RenderJobStatus.SUCCEEDED
    assert events[-1].stage is PipelineStage.PREVIEW_RENDER


def test_terminal_replay_closes_after_one_terminal_event_without_duplicates(tmp_path: Path) -> None:
    chunks = list(
        service(tmp_path).event_stream(Principal(OWNER_ID), JOB_ID, EventCursor.parse("2"))
    )

    terminal = [chunk for chunk in chunks if b"event: render_job" in chunk]
    assert len(terminal) == 1
    assert b"id: 3\n" in terminal[0]
    assert b'"status":"succeeded"' in terminal[0]


def test_nonterminal_stream_emits_a_legal_comment_heartbeat(tmp_path: Path) -> None:
    engine = migrated_engine(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM job_events WHERE render_job_id = :id"), {"id": str(JOB_ID)}
        )
        connection.execute(
            text("UPDATE render_jobs SET status = 'running', state_version = 3 WHERE id = :id"),
            {"id": str(JOB_ID)},
        )
        connection.execute(
            text("DELETE FROM job_events WHERE render_job_id = :id"), {"id": str(JOB_ID)}
        )
    stream = DeliveryService(engine, tmp_path / "artifacts", poll_seconds=0.1).event_stream(
        Principal(OWNER_ID),
        JOB_ID,
        EventCursor.parse("0"),
    )

    assert next(stream) == b"retry: 1000\n\n"
    assert next(stream) == b": keepalive\n\n"


def test_event_replay_survives_service_restart(tmp_path: Path) -> None:
    engine = migrated_engine(tmp_path)
    first = DeliveryService(engine, tmp_path / "artifacts")
    events = first.events(Principal(OWNER_ID), JOB_ID, EventCursor.parse("0"))
    assert [event.event_id for event in events] == [1, 2, 3]

    restarted = DeliveryService(create_engine(str(engine.url)), tmp_path / "artifacts")
    replay = restarted.events(Principal(OWNER_ID), JOB_ID, EventCursor.parse("2"))
    assert [event.event_id for event in replay] == [3]


def test_event_owner_mismatch_and_unknown_job_have_the_same_not_found_result(
    tmp_path: Path,
) -> None:
    delivery = service(tmp_path)
    requests = ((Principal(OTHER_OWNER_ID), JOB_ID), (Principal(OWNER_ID), UUID(int=999)))
    for principal, job_id in requests:
        with pytest.raises(DeliveryNotFound) as error:
            delivery.events(principal, job_id, EventCursor.parse("0"))
        assert error.value.public_payload() == {
            "error": {"code": "render_job_not_found", "message": "Render job was not found."}
        }


def test_artifact_is_served_from_db_relative_path_with_strict_mime_and_headers(
    tmp_path: Path,
) -> None:
    delivery = service(tmp_path)
    content = b"mp4-bytes"
    relative_path = "job/attempt-1/video.mp4"
    path = tmp_path / "artifacts" / relative_path
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    _insert_artifact(
        delivery,
        kind=ArtifactKind.VIDEO,
        relative_path=relative_path,
        content=content,
    )

    opened = delivery.artifact(Principal(OWNER_ID), ARTIFACT_ID, attachment=False)

    assert opened.path == path
    assert opened.media_type == "video/mp4"
    assert opened.headers == {
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    assert opened.filename is None


def test_artifact_download_sets_attachment_and_refuses_python_kind(tmp_path: Path) -> None:
    delivery = service(tmp_path)
    content = b"{}"
    relative_path = "job/attempt-1/metadata.json"
    path = tmp_path / "artifacts" / relative_path
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    _insert_artifact(
        delivery,
        kind=ArtifactKind.METADATA,
        relative_path=relative_path,
        content=content,
    )

    opened = delivery.artifact(Principal(OWNER_ID), ARTIFACT_ID, attachment=True)

    assert opened.media_type == "application/json"
    assert opened.filename == "metadata.json"


@pytest.mark.parametrize(
    ("kind", "filename", "expected_mime"),
    (
        (ArtifactKind.VIDEO, "video.mp4", "video/mp4"),
        (ArtifactKind.THUMBNAIL, "thumbnail.jpg", "image/jpeg"),
        (ArtifactKind.RENDER_LOG, "render.log", "text/plain"),
        (ArtifactKind.METADATA, "metadata.json", "application/json"),
    ),
)
def test_artifact_kind_uses_only_the_frozen_mime_allowlist(
    tmp_path: Path,
    kind: ArtifactKind,
    filename: str,
    expected_mime: str,
) -> None:
    delivery = service(tmp_path)
    content = b"artifact"
    path = tmp_path / "artifacts" / filename
    path.write_bytes(content)
    _insert_artifact(delivery, kind=kind, relative_path=filename, content=content)

    opened = delivery.artifact(Principal(OWNER_ID), ARTIFACT_ID, attachment=False)

    assert opened.media_type == expected_mime


@pytest.mark.parametrize("attack", ["../escape.mp4", "/tmp/escape.mp4"])
def test_artifact_path_escape_is_hidden_as_not_found(tmp_path: Path, attack: str) -> None:
    delivery = service(tmp_path)
    _insert_artifact(delivery, kind=ArtifactKind.VIDEO, relative_path=attack, content=b"ignored")

    with pytest.raises(DeliveryNotFound):
        delivery.artifact(Principal(OWNER_ID), ARTIFACT_ID, attachment=False)


def test_artifact_symlink_hash_size_and_owner_fail_closed_as_not_found(tmp_path: Path) -> None:
    delivery = service(tmp_path)
    root = tmp_path / "artifacts"
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    (root / "linked.mp4").symlink_to(outside)
    _insert_artifact(
        delivery,
        kind=ArtifactKind.VIDEO,
        relative_path="linked.mp4",
        content=b"outside",
    )

    with pytest.raises(DeliveryNotFound):
        delivery.artifact(Principal(OWNER_ID), ARTIFACT_ID, attachment=False)
    with pytest.raises(DeliveryNotFound):
        delivery.artifact(Principal(OTHER_OWNER_ID), ARTIFACT_ID, attachment=False)


@pytest.mark.parametrize("actual", [b"wrong", b"short"])
def test_artifact_hash_or_size_mismatch_is_hidden_as_not_found(
    tmp_path: Path, actual: bytes
) -> None:
    delivery = service(tmp_path)
    expected = b"known"
    path = tmp_path / "artifacts" / "job" / "video.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(actual)
    _insert_artifact(
        delivery,
        kind=ArtifactKind.VIDEO,
        relative_path="job/video.mp4",
        content=expected,
    )

    with pytest.raises(DeliveryNotFound):
        delivery.artifact(Principal(OWNER_ID), ARTIFACT_ID, attachment=False)


def test_router_replays_sse_with_bounded_cursor_and_no_terminal_duplicate(tmp_path: Path) -> None:
    delivery = service(tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session_principal] = lambda: session_principal(OWNER_ID)
    app.dependency_overrides[get_delivery_service] = lambda: delivery
    with TestClient(app) as client:
        response = client.get(
            f"/render-jobs/{JOB_ID}/events",
            headers={"Last-Event-ID": "2"},
        )
        malformed = client.get(
            f"/render-jobs/{JOB_ID}/events",
            headers={"Last-Event-ID": "-1"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-store"
    assert response.text.count("event: render_job") == 1
    assert "id: 3" in response.text
    assert malformed.status_code == 422
    assert malformed.json() == {
        "error": {"code": "invalid_event_cursor", "message": "Event cursor was invalid."}
    }


def test_router_returns_the_stable_auth_error_without_a_session_cookie(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_delivery_service] = lambda: service(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/render-jobs/{JOB_ID}/events")

    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "authentication_failed", "message": "Authentication failed."}
    }


def test_router_hides_cross_owner_artifact_and_applies_delivery_headers(tmp_path: Path) -> None:
    delivery = service(tmp_path)
    content = b"metadata"
    path = tmp_path / "artifacts" / "job" / "metadata.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    _insert_artifact(
        delivery,
        kind=ArtifactKind.METADATA,
        relative_path="job/metadata.json",
        content=content,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session_principal] = lambda: session_principal(OTHER_OWNER_ID)
    app.dependency_overrides[get_delivery_service] = lambda: delivery
    with TestClient(app) as client:
        denied = client.get(f"/artifacts/{ARTIFACT_ID}")
    app.dependency_overrides[get_session_principal] = lambda: session_principal(OWNER_ID)
    with TestClient(app) as client:
        downloaded = client.get(f"/artifacts/{ARTIFACT_ID}/download")

    assert denied.status_code == 404
    assert denied.json() == {
        "error": {"code": "artifact_not_found", "message": "Artifact was not found."}
    }
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("application/json")
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert downloaded.headers["content-disposition"] == 'attachment; filename="metadata.json"'


def _insert_artifact(
    delivery: DeliveryService,
    *,
    kind: ArtifactKind,
    relative_path: str,
    content: bytes,
) -> None:
    with delivery.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO artifacts (id, project_id, owner_id, render_job_id, kind, "
                "relative_path, "
                "sha256, byte_size, created_at) VALUES "
                "(:id, :project_id, :owner_id, :render_job_id, :kind, :relative_path, "
                ":sha256, :byte_size, :created_at)"
            ),
            {
                "id": str(ARTIFACT_ID),
                "project_id": "00000000-0000-0000-0000-000000000002",
                "owner_id": str(OWNER_ID),
                "render_job_id": str(JOB_ID),
                "kind": kind.value,
                "relative_path": relative_path,
                "sha256": sha256(content).hexdigest(),
                "byte_size": len(content),
                "created_at": "2026-08-05T00:00:00+00:00",
            },
        )
