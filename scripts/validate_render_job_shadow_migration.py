"""Validate the SQLite RenderJob typed-source rebuild on an explicit /tmp database.

This tool is deliberately unable to open a project or production database.  It proves
the offline shadow-table primitive before that primitive is integrated into Alembic.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from manim_workbench_api.database_migrations import rebuild_render_jobs as _rebuild_connection

TEMP_ROOT = Path("/tmp").resolve()

_LEGACY_COLUMNS = (
    "id",
    "project_id",
    "owner_id",
    "code_version_id",
    "profile",
    "status",
    "idempotency_key",
    "created_at",
    "started_at",
    "finished_at",
    "failure_code",
    "attempt_count",
    "lease_owner",
    "lease_token",
    "lease_expires_at",
    "heartbeat_at",
    "cancellation_requested_at",
    "state_version",
    "concat_group_id",
    "segment_index",
)


@dataclass(frozen=True)
class RebuildEvidence:
    database_path: str
    backup_path: str
    mode: str
    render_job_count: int
    foreign_key_check: str
    integrity_check: str


def _temporary_path(path: Path, *, must_exist: bool) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_relative_to(TEMP_ROOT):
        raise ValueError("shadow migration validation is restricted to /tmp")
    if must_exist and not resolved.is_file():
        raise ValueError("temporary database does not exist")
    if not must_exist and resolved.exists():
        raise ValueError("backup path already exists")
    return resolved


def _render_jobs_ddl(*, typed_source: bool) -> str:
    code_nullability = "" if typed_source else " NOT NULL"
    typed_column = "program_render_segment_id VARCHAR(36)," if typed_source else ""
    typed_check = (
        "CONSTRAINT ck_render_jobs_exactly_one_source CHECK "
        "((code_version_id IS NULL) != (program_render_segment_id IS NULL)),"
        if typed_source
        else ""
    )
    return f"""
        CREATE TABLE render_jobs_shadow (
            id VARCHAR(36) NOT NULL,
            project_id VARCHAR(36) NOT NULL,
            owner_id VARCHAR(36) NOT NULL,
            code_version_id VARCHAR(36){code_nullability},
            {typed_column}
            profile VARCHAR(20) NOT NULL,
            status VARCHAR(20) NOT NULL,
            idempotency_key VARCHAR(128) NOT NULL,
            created_at VARCHAR(35) NOT NULL,
            started_at VARCHAR(35),
            finished_at VARCHAR(35),
            failure_code VARCHAR(100),
            attempt_count INTEGER DEFAULT '0' NOT NULL,
            lease_owner VARCHAR(100),
            lease_token VARCHAR(64),
            lease_expires_at VARCHAR(35),
            heartbeat_at VARCHAR(35),
            cancellation_requested_at VARCHAR(35),
            state_version INTEGER DEFAULT '0' NOT NULL,
            concat_group_id VARCHAR(36),
            segment_index INTEGER,
            PRIMARY KEY (id),
            CONSTRAINT ck_render_jobs_attempt_count CHECK (attempt_count >= 0),
            CONSTRAINT ck_render_jobs_state_version CHECK (state_version >= 0),
            {typed_check}
            FOREIGN KEY(project_id) REFERENCES projects (id),
            FOREIGN KEY(code_version_id) REFERENCES code_versions (id),
            UNIQUE (idempotency_key),
            FOREIGN KEY(owner_id) REFERENCES users (id)
        )
    """


def _create_runtime_schema(database: sqlite3.Connection) -> None:
    database.execute(
        "CREATE INDEX ix_render_jobs_recovery ON render_jobs (status, lease_expires_at)"
    )
    database.execute(
        """
        CREATE TRIGGER render_jobs_phase8_event_after_insert
        AFTER INSERT ON render_jobs
        BEGIN
          INSERT INTO job_events (
            render_job_id, owner_id, state_version, stage, status, error_code, created_at
          ) VALUES (
            NEW.id, NEW.owner_id, NEW.state_version,
            CASE NEW.profile WHEN 'preview' THEN 'preview_render' ELSE 'final_render' END,
            NEW.status, NEW.failure_code, NEW.created_at
          );
        END
        """
    )
    database.execute(
        """
        CREATE TRIGGER render_jobs_phase8_event_after_update
        AFTER UPDATE ON render_jobs
        WHEN NEW.state_version != OLD.state_version
          AND (NEW.status != OLD.status
               OR NEW.cancellation_requested_at IS NOT OLD.cancellation_requested_at)
        BEGIN
          INSERT INTO job_events (
            render_job_id, owner_id, state_version, stage, status, error_code, created_at
          ) VALUES (
            NEW.id, NEW.owner_id, NEW.state_version,
            CASE NEW.profile WHEN 'preview' THEN 'preview_render' ELSE 'final_render' END,
            NEW.status, NEW.failure_code, COALESCE(NEW.finished_at, NEW.started_at, NEW.created_at)
          );
        END
        """
    )


def _validate_integrity(database: sqlite3.Connection) -> tuple[str, str]:
    foreign_key_violations = database.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_violations:
        raise RuntimeError(f"foreign key violations: {foreign_key_violations}")
    integrity = database.execute("PRAGMA integrity_check").fetchone()
    if integrity != ("ok",):
        raise RuntimeError(f"integrity_check failed: {integrity}")
    return "ok", "ok"


def _backup(database: sqlite3.Connection, backup_path: Path) -> None:
    database.execute("PRAGMA wal_checkpoint(FULL)")
    backup = sqlite3.connect(backup_path)
    try:
        database.backup(backup)
        integrity = backup.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise RuntimeError(f"backup integrity_check failed: {integrity}")
    finally:
        backup.close()


def rebuild_render_jobs(
    database_path: Path,
    backup_path: Path,
    *,
    typed_source: bool,
) -> RebuildEvidence:
    database_path = _temporary_path(database_path, must_exist=True)
    backup_path = _temporary_path(backup_path, must_exist=False)
    database = sqlite3.connect(database_path, isolation_level=None, timeout=5)
    try:
        core = _rebuild_connection(database, backup_path, typed_source=typed_source)
        return RebuildEvidence(
            database_path=str(database_path),
            backup_path=core.backup_path or "",
            mode=core.mode,
            render_job_count=core.render_job_count,
            foreign_key_check=core.foreign_key_check,
            integrity_check=core.integrity_check,
        )
    finally:
        database.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--mode", choices=("upgrade", "downgrade"), required=True)
    arguments = parser.parse_args()
    evidence = rebuild_render_jobs(
        arguments.database,
        arguments.backup,
        typed_source=arguments.mode == "upgrade",
    )
    print(json.dumps(asdict(evidence), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
