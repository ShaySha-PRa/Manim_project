from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import Engine, text


class WorkflowTaskKind(str, Enum):
    SCENE_PROGRAM = "scene_program"
    COMPOSITION = "composition"
    DIRECTOR_PLAN = "director_plan"


@dataclass(frozen=True, slots=True)
class WorkflowTask:
    id: UUID
    kind: WorkflowTaskKind
    run_id: UUID
    project_id: UUID
    owner_id: UUID
    idempotency_key: str
    payload: dict[str, Any]
    status: str
    attempt_count: int
    lease_owner: str | None
    lease_token: str | None
    lease_expires_at: datetime | None


class WorkflowTaskNotifier(Protocol):
    def wake(self, kind: WorkflowTaskKind, task_id: UUID) -> None: ...


class WorkflowTaskQueue:
    """SQLite-authoritative workflow queue; notifier failures never lose tasks."""

    def __init__(self, engine: Engine, notifier: WorkflowTaskNotifier | None = None) -> None:
        self._engine = engine
        self._notifier = notifier

    def submit(
        self,
        *,
        kind: WorkflowTaskKind,
        run_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        idempotency_key: str,
        payload: dict[str, Any],
        now: datetime | None = None,
    ) -> WorkflowTask:
        current_time = now or datetime.now(timezone.utc)
        table = {
            WorkflowTaskKind.SCENE_PROGRAM: "scene_block_runs",
            WorkflowTaskKind.COMPOSITION: "workflow_composition_runs",
            WorkflowTaskKind.DIRECTOR_PLAN: "workflow_director_plans",
        }[kind]
        with self._engine.begin() as connection:
            boundary = connection.execute(
                text(
                    f"SELECT r.id FROM {table} r JOIN projects p ON p.id=r.project_id "
                    f"WHERE r.id=:run_id AND r.project_id=:project_id "
                    f"AND r.owner_id=:owner_id AND p.owner_id=:owner_id "
                    f"AND p.archived_at IS NULL"
                ),
                {
                    "run_id": str(run_id),
                    "project_id": str(project_id),
                    "owner_id": str(owner_id),
                },
            ).one_or_none()
            if boundary is None:
                raise ValueError("workflow task run was not found")
            existing = (
                connection.execute(
                    text(
                        "SELECT * FROM workflow_tasks WHERE kind=:kind AND run_id=:run_id "
                        "AND project_id=:project_id AND owner_id=:owner_id"
                    ),
                    {
                        "kind": kind.value,
                        "run_id": str(run_id),
                        "project_id": str(project_id),
                        "owner_id": str(owner_id),
                    },
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if existing["idempotency_key"] != idempotency_key:
                    raise ValueError("workflow task idempotency conflict")
                return self._from_row(existing)
            task_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO workflow_tasks "
                    "(id,kind,run_id,project_id,owner_id,idempotency_key,payload_json,status,"
                    "attempt_count,available_at,created_at,updated_at) VALUES "
                    "(:id,:kind,:run_id,:project_id,:owner_id,:idempotency_key,:payload,'queued',"
                    "0,:now,:now,:now)"
                ),
                {
                    "id": str(task_id),
                    "kind": kind.value,
                    "run_id": str(run_id),
                    "project_id": str(project_id),
                    "owner_id": str(owner_id),
                    "idempotency_key": idempotency_key,
                    "payload": json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    "now": current_time.isoformat(),
                },
            )
            row = connection.execute(
                text("SELECT * FROM workflow_tasks WHERE id=:id"), {"id": str(task_id)}
            ).mappings().one()
        if self._notifier is not None:
            try:
                self._notifier.wake(kind, task_id)
            except OSError:
                pass
        return self._from_row(row)

    def claim(
        self,
        kind: WorkflowTaskKind,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> WorkflowTask | None:
        if not 5 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be in the range [5, 3600]")
        current_time = now or datetime.now(timezone.utc)
        expires = current_time + timedelta(seconds=lease_seconds)
        token = secrets.token_hex(32)
        with self._engine.begin() as connection:
            candidate = connection.execute(
                text(
                    "SELECT id FROM workflow_tasks WHERE kind=:kind AND available_at<=:now "
                    "AND (status='queued' OR (status='leased' AND lease_expires_at<=:now)) "
                    "ORDER BY created_at,id LIMIT 1"
                ),
                {"kind": kind.value, "now": current_time.isoformat()},
            ).scalar_one_or_none()
            if candidate is None:
                return None
            row = (
                connection.execute(
                    text(
                        "UPDATE workflow_tasks SET status='leased',attempt_count=attempt_count+1,"
                        "lease_owner=:worker,lease_token=:token,lease_expires_at=:expires,"
                        "updated_at=:now WHERE id=:id AND "
                        "(status='queued' OR (status='leased' AND lease_expires_at<=:now)) "
                        "RETURNING *"
                    ),
                    {
                        "worker": worker_id,
                        "token": token,
                        "expires": expires.isoformat(),
                        "now": current_time.isoformat(),
                        "id": str(candidate),
                    },
                )
                .mappings()
                .one_or_none()
            )
        return self._from_row(row) if row is not None else None

    def complete(
        self, task_id: UUID, lease_token: str, *, now: datetime | None = None
    ) -> bool:
        current_time = now or datetime.now(timezone.utc)
        with self._engine.begin() as connection:
            changed = connection.execute(
                text(
                    "UPDATE workflow_tasks SET status='complete',completed_at=:now,updated_at=:now,"
                    "lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL "
                    "WHERE id=:id AND status='leased' AND lease_token=:token "
                    "AND lease_expires_at>:now"
                ),
                {
                    "id": str(task_id),
                    "token": lease_token,
                    "now": current_time.isoformat(),
                },
            ).rowcount
        return changed == 1

    def release(
        self,
        task_id: UUID,
        lease_token: str,
        *,
        retry_at: datetime,
        now: datetime | None = None,
    ) -> bool:
        current_time = now or datetime.now(timezone.utc)
        if retry_at <= current_time or retry_at > current_time + timedelta(minutes=5):
            raise ValueError("workflow retry_at must be within the next five minutes")
        with self._engine.begin() as connection:
            changed = connection.execute(
                text(
                    "UPDATE workflow_tasks SET status='queued',available_at=:retry,"
                    "lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,updated_at=:now "
                    "WHERE id=:id AND status='leased' AND lease_token=:token "
                    "AND lease_expires_at>:now"
                ),
                {"id": str(task_id), "token": lease_token,
                 "retry": retry_at.isoformat(), "now": current_time.isoformat()},
            ).rowcount
        return changed == 1

    @staticmethod
    def _from_row(row: Any) -> WorkflowTask:
        return WorkflowTask(
            id=UUID(str(row["id"])),
            kind=WorkflowTaskKind(str(row["kind"])),
            run_id=UUID(str(row["run_id"])),
            project_id=UUID(str(row["project_id"])),
            owner_id=UUID(str(row["owner_id"])),
            idempotency_key=str(row["idempotency_key"]),
            payload=json.loads(row["payload_json"]),
            status=str(row["status"]),
            attempt_count=int(row["attempt_count"]),
            lease_owner=str(row["lease_owner"]) if row["lease_owner"] else None,
            lease_token=str(row["lease_token"]) if row["lease_token"] else None,
            lease_expires_at=(
                datetime.fromisoformat(str(row["lease_expires_at"]))
                if row["lease_expires_at"]
                else None
            ),
        )
