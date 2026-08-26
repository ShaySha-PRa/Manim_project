"""Offline SQLite shadow-table rebuild for RenderJob typed sources."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

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


@dataclass(frozen=True, slots=True)
class RebuildEvidence:
    backup_path: str | None
    mode: str
    render_job_count: int
    foreign_key_check: str
    integrity_check: str
    rebuilt: bool


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
    if backup_path.exists():
        raise RuntimeError(f"refusing to overwrite migration backup: {backup_path}")
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    database.execute("PRAGMA wal_checkpoint(FULL)")
    backup = sqlite3.connect(backup_path)
    try:
        database.backup(backup)
        integrity = backup.execute("PRAGMA integrity_check").fetchone()
        if integrity != ("ok",):
            raise RuntimeError(f"backup integrity_check failed: {integrity}")
    finally:
        backup.close()


def _source_shape(database: sqlite3.Connection) -> tuple[bool, bool]:
    columns = {
        str(row[1]): bool(row[3])
        for row in database.execute("PRAGMA table_info(render_jobs)")
    }
    if not columns:
        raise RuntimeError("render_jobs table does not exist")
    has_typed_column = "program_render_segment_id" in columns
    code_version_not_null = columns.get("code_version_id") is True
    return has_typed_column, code_version_not_null


def _validate_requested_shape(
    database: sqlite3.Connection, *, typed_source: bool
) -> None:
    has_typed_column, code_version_not_null = _source_shape(database)
    if typed_source:
        if not has_typed_column or code_version_not_null:
            raise RuntimeError("render_jobs typed-source schema is incomplete")
        table_sql = database.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='render_jobs'"
        ).fetchone()
        if table_sql is None or "ck_render_jobs_exactly_one_source" not in str(table_sql[0]):
            raise RuntimeError("render_jobs typed-source constraint is missing")
    elif has_typed_column or not code_version_not_null:
        raise RuntimeError("render_jobs legacy source schema is incomplete")


def validate_render_jobs_shape(
    database: sqlite3.Connection, *, typed_source: bool
) -> tuple[str, str]:
    """Validate source columns, constraints, child references, and SQLite integrity."""

    if database.execute("PRAGMA foreign_keys").fetchone() != (1,):
        raise RuntimeError("SQLite foreign keys must be enabled for schema validation")
    _validate_requested_shape(database, typed_source=typed_source)
    return _validate_integrity(database)


def rebuild_render_jobs(
    database: sqlite3.Connection,
    backup_path: Path,
    *,
    typed_source: bool,
) -> RebuildEvidence:
    """Rebuild RenderJob source columns, preserving all pre-existing evidence.

    The caller must stop API/Runner writes and provide a file-backed SQLite connection.
    The primitive deliberately owns its short ``BEGIN IMMEDIATE`` transaction.
    """

    if database.in_transaction:
        raise RuntimeError("RenderJob rebuild requires a connection outside a transaction")
    database.execute("PRAGMA foreign_keys=ON")
    if database.execute("PRAGMA foreign_keys").fetchone() != (1,):
        raise RuntimeError("SQLite foreign keys must be enabled before migration")
    foreign_key_check, integrity_check = _validate_integrity(database)
    has_typed_column, code_version_not_null = _source_shape(database)
    already_requested = (
        has_typed_column and not code_version_not_null
        if typed_source
        else not has_typed_column and code_version_not_null
    )
    if already_requested:
        _validate_requested_shape(database, typed_source=typed_source)
        count = int(database.execute("SELECT COUNT(*) FROM render_jobs").fetchone()[0])
        return RebuildEvidence(
            backup_path=None,
            mode="upgrade" if typed_source else "downgrade",
            render_job_count=count,
            foreign_key_check=foreign_key_check,
            integrity_check=integrity_check,
            rebuilt=False,
        )
    if not typed_source:
        scientific_jobs = int(
            database.execute(
                "SELECT COUNT(*) FROM render_jobs "
                "WHERE program_render_segment_id IS NOT NULL"
            ).fetchone()[0]
        )
        if scientific_jobs:
            raise RuntimeError(
                "cannot downgrade while RenderJobs reference ProgramRenderSegments"
            )

    _backup(database, backup_path)
    legacy_columns = ",".join(_LEGACY_COLUMNS)
    insert_columns = legacy_columns + (
        ",program_render_segment_id" if typed_source else ""
    )
    select_columns = legacy_columns + (",NULL" if typed_source else "")
    database.execute("PRAGMA foreign_keys=OFF")
    if database.execute("PRAGMA foreign_keys").fetchone() != (0,):
        raise RuntimeError("could not enter SQLite foreign-key rebuild window")
    try:
        database.execute("BEGIN IMMEDIATE")
        before_rows = database.execute(
            f"SELECT {legacy_columns} FROM render_jobs ORDER BY id"
        ).fetchall()
        database.execute(_render_jobs_ddl(typed_source=typed_source))
        database.execute(
            f"INSERT INTO render_jobs_shadow ({insert_columns}) "
            f"SELECT {select_columns} FROM render_jobs"
        )
        copied_rows = database.execute(
            f"SELECT {legacy_columns} FROM render_jobs_shadow ORDER BY id"
        ).fetchall()
        if copied_rows != before_rows:
            raise RuntimeError("RenderJob shadow copy changed existing rows")
        database.execute("DROP TABLE render_jobs")
        database.execute("ALTER TABLE render_jobs_shadow RENAME TO render_jobs")
        _create_runtime_schema(database)
        _validate_requested_shape(database, typed_source=typed_source)
        foreign_key_check, integrity_check = _validate_integrity(database)
        database.commit()
    except BaseException:
        database.rollback()
        raise
    finally:
        database.execute("PRAGMA foreign_keys=ON")
        if database.execute("PRAGMA foreign_keys").fetchone() != (1,):
            raise RuntimeError("SQLite foreign keys were not restored")
    return RebuildEvidence(
        backup_path=str(backup_path),
        mode="upgrade" if typed_source else "downgrade",
        render_job_count=len(before_rows),
        foreign_key_check=foreign_key_check,
        integrity_check=integrity_check,
        rebuilt=True,
    )
