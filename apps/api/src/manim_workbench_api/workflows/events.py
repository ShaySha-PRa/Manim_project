from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Engine, text

from .errors import WORKFLOW_NOT_FOUND

_MAX_EVENT_CURSOR = 1_000_000
_MAX_REPLAY_EVENTS = 1_000
_SCENE_TERMINAL = {"asset_required", "failed", "needs_confirmation", "succeeded"}
_COMPOSITION_TERMINAL = {"failed", "not_ready_to_compose", "succeeded"}


@dataclass(frozen=True)
class WorkflowEventCursor:
    value: int

    @classmethod
    def parse(cls, raw: str | None) -> WorkflowEventCursor:
        if raw is None:
            return cls(-1)
        if not raw.isascii() or not raw.isdecimal():
            raise ValueError("event cursor must be a non-negative decimal integer")
        value = int(raw)
        if value > _MAX_EVENT_CURSOR:
            raise ValueError("event cursor is too large")
        return cls(value)


@dataclass(frozen=True)
class WorkflowRunEvent:
    run_id: UUID
    state_version: int
    status: str
    error_code: str | None
    created_at: str


class WorkflowEventService:
    """Replay owner-scoped append-only Workflow events from SQLite."""

    def __init__(self, engine: Engine, *, poll_seconds: float = 1.0) -> None:
        self._engine = engine
        self._poll_seconds = min(max(poll_seconds, 0.1), 10.0)

    def scene_events(
        self, run_id: UUID, owner_id: UUID, cursor: WorkflowEventCursor
    ) -> tuple[WorkflowRunEvent, ...]:
        return self._events(
            run_table="scene_block_runs",
            event_table="scene_block_run_events",
            run_id=run_id,
            owner_id=owner_id,
            cursor=cursor,
        )

    def composition_events(
        self, run_id: UUID, owner_id: UUID, cursor: WorkflowEventCursor
    ) -> tuple[WorkflowRunEvent, ...]:
        return self._events(
            run_table="workflow_composition_runs",
            event_table="workflow_composition_run_events",
            run_id=run_id,
            owner_id=owner_id,
            cursor=cursor,
        )

    def scene_event_stream(
        self, run_id: UUID, owner_id: UUID, cursor: WorkflowEventCursor
    ) -> Iterable[bytes]:
        return self._event_stream(
            self.scene_events,
            run_id,
            owner_id,
            cursor,
            event_name="scene_block_run",
            terminal_statuses=_SCENE_TERMINAL,
            terminal_check=lambda: self._is_terminal(
                "scene_block_runs", "scene_block_run_events", run_id, owner_id, _SCENE_TERMINAL
            ),
        )

    def composition_event_stream(
        self, run_id: UUID, owner_id: UUID, cursor: WorkflowEventCursor
    ) -> Iterable[bytes]:
        return self._event_stream(
            self.composition_events,
            run_id,
            owner_id,
            cursor,
            event_name="composition_run",
            terminal_statuses=_COMPOSITION_TERMINAL,
            terminal_check=lambda: self._is_terminal(
                "workflow_composition_runs",
                "workflow_composition_run_events",
                run_id,
                owner_id,
                _COMPOSITION_TERMINAL,
            ),
        )

    def _events(
        self,
        *,
        run_table: str,
        event_table: str,
        run_id: UUID,
        owner_id: UUID,
        cursor: WorkflowEventCursor,
    ) -> tuple[WorkflowRunEvent, ...]:
        if (run_table, event_table) not in {
            ("scene_block_runs", "scene_block_run_events"),
            ("workflow_composition_runs", "workflow_composition_run_events"),
        }:
            raise ValueError("unsupported workflow event source")
        values = {"run_id": str(run_id), "owner_id": str(owner_id)}
        with self._engine.connect() as connection:
            visible = connection.execute(
                text(
                    f"SELECT r.id FROM {run_table} r JOIN projects p ON p.id=r.project_id "
                    "WHERE r.id=:run_id AND r.owner_id=:owner_id "
                    "AND p.owner_id=:owner_id AND p.archived_at IS NULL"
                ),
                values,
            ).scalar_one_or_none()
            if visible is None:
                raise WORKFLOW_NOT_FOUND
            rows = connection.execute(
                text(
                    f"SELECT e.run_id,e.state_version,e.status,e.error_code,e.created_at "
                    f"FROM {event_table} e WHERE e.run_id=:run_id "
                    "AND e.owner_id=:owner_id AND e.state_version>:cursor "
                    "ORDER BY e.state_version LIMIT :limit"
                ),
                {
                    **values,
                    "cursor": cursor.value,
                    "limit": _MAX_REPLAY_EVENTS,
                },
            ).mappings()
            return tuple(
                WorkflowRunEvent(
                    run_id=UUID(str(row["run_id"])),
                    state_version=int(row["state_version"]),
                    status=str(row["status"]),
                    error_code=(str(row["error_code"]) if row["error_code"] else None),
                    created_at=str(row["created_at"]),
                )
                for row in rows
            )

    def _event_stream(
        self,
        loader,  # type: ignore[no-untyped-def]
        run_id: UUID,
        owner_id: UUID,
        cursor: WorkflowEventCursor,
        *,
        event_name: str,
        terminal_statuses: set[str],
        terminal_check: Callable[[], bool],
    ) -> Iterable[bytes]:
        current = cursor
        yield b"retry: 1000\n\n"
        while True:
            events = loader(run_id, owner_id, current)
            if events:
                for event in events:
                    yield _encode_event(event_name, event)
                    current = WorkflowEventCursor(event.state_version)
                    if event.status in terminal_statuses:
                        return
                continue
            if terminal_check():
                return
            yield b": keepalive\n\n"
            time.sleep(self._poll_seconds)

    def _is_terminal(
        self,
        run_table: str,
        event_table: str,
        run_id: UUID,
        owner_id: UUID,
        terminal_statuses: set[str],
    ) -> bool:
        if (run_table, event_table) not in {
            ("scene_block_runs", "scene_block_run_events"),
            ("workflow_composition_runs", "workflow_composition_run_events"),
        }:
            raise ValueError("unsupported workflow event source")
        with self._engine.connect() as connection:
            status = connection.execute(
                text(
                    f"SELECT e.status FROM {event_table} e JOIN {run_table} r ON r.id=e.run_id "
                    "JOIN projects p ON p.id=r.project_id WHERE r.id=:run_id "
                    "AND r.owner_id=:owner_id AND e.owner_id=:owner_id "
                    "AND p.owner_id=:owner_id AND p.archived_at IS NULL "
                    "ORDER BY e.state_version DESC LIMIT 1"
                ),
                {"run_id": str(run_id), "owner_id": str(owner_id)},
            ).scalar_one_or_none()
        if status is None:
            raise WORKFLOW_NOT_FOUND
        return str(status) in terminal_statuses


def _encode_event(event_name: str, event: WorkflowRunEvent) -> bytes:
    payload = json.dumps(
        {
            "created_at": event.created_at,
            "error_code": event.error_code,
            "run_id": str(event.run_id),
            "state_version": event.state_version,
            "status": event.status,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        f"id: {event.state_version}\n"
        f"event: {event_name}\n"
        f"data: {payload}\n\n"
    ).encode()
