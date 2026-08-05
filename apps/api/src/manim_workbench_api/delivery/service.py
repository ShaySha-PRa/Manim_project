from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
from uuid import UUID

from manim_workbench_contracts import JobEvent, PipelineStage, RenderJobStatus
from manim_workbench_contracts.models import ArtifactKind
from sqlalchemy import Engine, text

from manim_workbench_api.auth.models import SessionPrincipal

_MAX_EVENT_CURSOR = 1_000_000
_MAX_REPLAY_EVENTS = 1_000
_TERMINAL_STATUSES = {
    RenderJobStatus.SUCCEEDED,
    RenderJobStatus.FAILED,
    RenderJobStatus.CANCELLED,
}
_MIME_TYPES = {
    ArtifactKind.VIDEO: "video/mp4",
    ArtifactKind.THUMBNAIL: "image/jpeg",
    ArtifactKind.RENDER_LOG: "text/plain",
    ArtifactKind.METADATA: "application/json",
}
_SAFE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, no-store",
}


@dataclass(frozen=True)
class EventCursor:
    value: int

    @classmethod
    def parse(cls, raw: str | None) -> EventCursor:
        if raw is None:
            return cls(0)
        if not raw.isascii() or not raw.isdecimal():
            raise ValueError("event cursor must be a non-negative decimal integer")
        value = int(raw)
        if value > _MAX_EVENT_CURSOR:
            raise ValueError("event cursor is too large")
        return cls(value)


@dataclass(frozen=True)
class OpenArtifact:
    path: Path
    media_type: str
    headers: dict[str, str]
    filename: str | None


class DeliveryNotFound(Exception):
    """Intentionally identical for absent, unauthorized and unsafe resources."""

    def __init__(self, resource: str) -> None:
        self._resource = resource
        super().__init__(resource)

    def public_payload(self) -> dict[str, object]:
        labels = {
            "render_job": ("render_job_not_found", "Render job was not found."),
            "artifact": ("artifact_not_found", "Artifact was not found."),
        }
        code, message = labels[self._resource]
        return {"error": {"code": code, "message": message}}


class DeliveryService:
    """Reads durable delivery data without exposing filesystem or tenant details."""

    def __init__(
        self,
        engine: Engine,
        artifact_root: Path,
        *,
        poll_seconds: float = 1.0,
    ) -> None:
        self.engine = engine
        artifact_root.mkdir(parents=True, exist_ok=True)
        self._artifact_root = artifact_root.resolve(strict=True)
        self._poll_seconds = min(max(poll_seconds, 0.1), 10.0)

    def events(
        self,
        principal: SessionPrincipal,
        job_id: UUID,
        cursor: EventCursor,
    ) -> tuple[JobEvent, ...]:
        owner_id = _owner_id(principal)
        with self.engine.connect() as connection:
            job = connection.execute(
                text("SELECT id FROM render_jobs WHERE id = :id AND owner_id = :owner_id"),
                {"id": str(job_id), "owner_id": str(owner_id)},
            ).first()
            if job is None:
                raise DeliveryNotFound("render_job")
            rows = connection.execute(
                text(
                    "SELECT id, render_job_id, state_version, stage, status, error_code, "
                    "created_at "
                    "FROM job_events WHERE render_job_id = :job_id AND owner_id = :owner_id "
                    "AND id > :cursor ORDER BY id ASC LIMIT :limit"
                ),
                {
                    "job_id": str(job_id),
                    "owner_id": str(owner_id),
                    "cursor": cursor.value,
                    "limit": _MAX_REPLAY_EVENTS,
                },
            ).mappings()
            return tuple(_job_event(row) for row in rows)

    def event_stream(
        self,
        principal: SessionPrincipal,
        job_id: UUID,
        cursor: EventCursor,
    ) -> Iterable[bytes]:
        """Replay durable events, then poll until a terminal event is sent."""

        current_cursor = cursor
        yield b"retry: 1000\n\n"
        while True:
            events = self.events(principal, job_id, current_cursor)
            if events:
                for event in events:
                    yield _encode_event(event)
                    current_cursor = EventCursor(event.event_id)
                    if event.status in _TERMINAL_STATUSES:
                        return
                continue
            if self._is_terminal(principal, job_id):
                return
            yield b": keepalive\n\n"
            time.sleep(self._poll_seconds)

    def artifact(
        self,
        principal: SessionPrincipal,
        artifact_id: UUID,
        *,
        attachment: bool,
    ) -> OpenArtifact:
        owner_id = _owner_id(principal)
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT artifacts.kind, artifacts.relative_path, artifacts.sha256, "
                        "artifacts.byte_size "
                        "FROM artifacts JOIN render_jobs ON "
                        "render_jobs.id = artifacts.render_job_id "
                        "WHERE artifacts.id = :artifact_id AND artifacts.owner_id = :owner_id "
                        "AND render_jobs.owner_id = :owner_id"
                    ),
                    {"artifact_id": str(artifact_id), "owner_id": str(owner_id)},
                )
                .mappings()
                .first()
            )
        if row is None:
            raise DeliveryNotFound("artifact")
        try:
            kind = ArtifactKind(str(row["kind"]))
            path = self._artifact_path(str(row["relative_path"]))
            expected_hash = str(row["sha256"])
            expected_size = int(row["byte_size"])
            if path.is_symlink() or not path.is_file() or path.stat().st_size != expected_size:
                raise ValueError("artifact is not a regular expected-size file")
            if sha256(path.read_bytes()).hexdigest() != expected_hash:
                raise ValueError("artifact hash differs from database")
        except (OSError, TypeError, ValueError):
            raise DeliveryNotFound("artifact") from None

        filename = path.name if attachment else None
        return OpenArtifact(
            path=path,
            media_type=_MIME_TYPES[kind],
            headers=dict(_SAFE_HEADERS),
            filename=filename,
        )

    def _is_terminal(self, principal: SessionPrincipal, job_id: UUID) -> bool:
        owner_id = _owner_id(principal)
        with self.engine.connect() as connection:
            status = connection.execute(
                text("SELECT status FROM render_jobs WHERE id = :id AND owner_id = :owner_id"),
                {"id": str(job_id), "owner_id": str(owner_id)},
            ).scalar_one_or_none()
        if status is None:
            raise DeliveryNotFound("render_job")
        try:
            return RenderJobStatus(str(status)) in _TERMINAL_STATUSES
        except ValueError:
            return True

    def _artifact_path(self, relative_path: str) -> Path:
        normalized = relative_path.replace("\\", "/")
        candidate = PurePosixPath(normalized)
        if not normalized or candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("artifact path is outside root")
        path = self._artifact_root
        for part in candidate.parts:
            path = path / part
            if path.is_symlink():
                raise ValueError("artifact path includes a symlink")
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(self._artifact_root):
            raise ValueError("artifact path resolves outside root")
        return path


def _owner_id(principal: SessionPrincipal) -> UUID:
    return principal.user_id


def _job_event(row: object) -> JobEvent:
    mapping = row  # SQLAlchemy RowMapping has typed mapping methods only at runtime.
    assert hasattr(mapping, "__getitem__")
    created_at = datetime.fromisoformat(str(mapping["created_at"]))  # type: ignore[index]
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return JobEvent(
        event_id=int(mapping["id"]),  # type: ignore[index]
        render_job_id=UUID(str(mapping["render_job_id"])),  # type: ignore[index]
        state_version=int(mapping["state_version"]),  # type: ignore[index]
        stage=PipelineStage(str(mapping["stage"])),  # type: ignore[index]
        status=RenderJobStatus(str(mapping["status"])),  # type: ignore[index]
        error_code=mapping["error_code"],  # type: ignore[index]
        created_at=created_at.astimezone(timezone.utc),
    )


def _encode_event(event: JobEvent) -> bytes:
    payload = event.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.event_id}\nevent: render_job\ndata: {encoded}\n\n".encode()
