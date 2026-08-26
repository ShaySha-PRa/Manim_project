"""Protected two-step orchestration for the RenderJob typed-source migration."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config

from .render_job_typed_sources import (
    rebuild_render_jobs,
    validate_render_jobs_shape,
)

REVISION_0008 = "0008_asset_versions"
REVISION_0009 = "0009_render_job_typed_sources"


class ProtectedMigrationError(RuntimeError):
    """The guarded migration or its recovery validation failed."""


@dataclass(frozen=True, slots=True)
class ProtectedMigrationEvidence:
    database_path: str
    backup_path: str
    mode: str
    previous_revision: str
    current_revision: str
    rebuilt: bool
    render_job_count: int
    foreign_key_check: str
    integrity_check: str


RevisionAction = Callable[[Config, str], None]


def _resolved_file(path: Path, *, must_exist: bool) -> Path:
    resolved = path.expanduser().resolve()
    if must_exist and not resolved.is_file():
        raise ProtectedMigrationError(f"database file does not exist: {resolved}")
    return resolved


def _connect(path: Path) -> sqlite3.Connection:
    database = sqlite3.connect(path, isolation_level=None, timeout=5)
    database.execute("PRAGMA foreign_keys=ON")
    if database.execute("PRAGMA foreign_keys").fetchone() != (1,):
        database.close()
        raise ProtectedMigrationError("could not enable SQLite foreign keys")
    return database


def _revision(database: sqlite3.Connection) -> str:
    row = database.execute("SELECT version_num FROM alembic_version").fetchone()
    if row is None or not isinstance(row[0], str):
        raise ProtectedMigrationError("database has no single Alembic revision")
    return row[0]


def _assert_exclusive_window(database: sqlite3.Connection) -> None:
    try:
        database.execute("BEGIN EXCLUSIVE")
        database.rollback()
    except sqlite3.OperationalError as error:
        database.rollback()
        raise ProtectedMigrationError(
            "database is busy; stop API and Runner before migration"
        ) from error


def _validate_backup(
    backup_path: Path, *, revision: str, typed_source: bool
) -> None:
    backup = _connect(backup_path)
    try:
        if _revision(backup) != revision:
            raise ProtectedMigrationError("backup revision does not match migration source")
        validate_render_jobs_shape(backup, typed_source=typed_source)
    finally:
        backup.close()


def _restore_backup(database_path: Path, backup_path: Path) -> None:
    temporary = database_path.with_name(
        f".{database_path.name}.restore-{uuid4().hex}.tmp"
    )
    source = sqlite3.connect(backup_path, isolation_level=None, timeout=5)
    target = sqlite3.connect(temporary, isolation_level=None, timeout=5)
    try:
        source.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ProtectedMigrationError("restored temporary database failed integrity_check")
    finally:
        target.close()
        source.close()
    try:
        for suffix in ("-wal", "-shm"):
            Path(f"{database_path}{suffix}").unlink(missing_ok=True)
        os.replace(temporary, database_path)
    finally:
        temporary.unlink(missing_ok=True)


def _default_revision_action(config: Config, target: str) -> None:
    current = _current_revision_from_url(config)
    if current == REVISION_0008 and target == REVISION_0009:
        command.upgrade(config, target)
    elif current == REVISION_0009 and target == REVISION_0008:
        command.downgrade(config, target)
    else:
        raise ProtectedMigrationError(
            f"unsupported protected revision transition: {current} -> {target}"
        )


def _current_revision_from_url(config: Config) -> str:
    url = config.get_main_option("sqlalchemy.url")
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ProtectedMigrationError("protected migration requires a SQLite file URL")
    database = _connect(Path(url.removeprefix(prefix)))
    try:
        return _revision(database)
    finally:
        database.close()


def run_protected_migration(
    *,
    database_path: Path,
    backup_path: Path,
    alembic_config_path: Path,
    mode: str,
    services_stopped: bool,
    revision_action: RevisionAction | None = None,
) -> ProtectedMigrationEvidence:
    """Rebuild source columns and atomically recover if revision marking fails."""

    if not services_stopped:
        raise ProtectedMigrationError(
            "explicit confirmation that API and Runner are stopped is required"
        )
    if mode not in {"upgrade", "downgrade"}:
        raise ProtectedMigrationError("mode must be upgrade or downgrade")
    database_path = _resolved_file(database_path, must_exist=True)
    backup_path = _resolved_file(backup_path, must_exist=False)
    if database_path == backup_path:
        raise ProtectedMigrationError("backup path must differ from database path")
    config_path = _resolved_file(alembic_config_path, must_exist=True)

    source_revision = REVISION_0008 if mode == "upgrade" else REVISION_0009
    target_revision = REVISION_0009 if mode == "upgrade" else REVISION_0008
    source_typed = mode == "downgrade"
    target_typed = mode == "upgrade"
    database = _connect(database_path)
    try:
        if _revision(database) != source_revision:
            raise ProtectedMigrationError(
                f"protected {mode} requires database head {source_revision}"
            )
        _assert_exclusive_window(database)
        try:
            validate_render_jobs_shape(database, typed_source=target_typed)
            already_prepared = True
        except RuntimeError:
            validate_render_jobs_shape(database, typed_source=source_typed)
            already_prepared = False
        if already_prepared:
            if not backup_path.is_file():
                raise ProtectedMigrationError(
                    "prepared intermediate schema requires its existing recovery backup"
                )
            _validate_backup(
                backup_path,
                revision=source_revision,
                typed_source=source_typed,
            )
        evidence = rebuild_render_jobs(
            database,
            backup_path,
            typed_source=target_typed,
        )
    finally:
        database.close()

    config = Config(str(config_path))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    action = revision_action or _default_revision_action
    try:
        action(config, target_revision)
    except BaseException as error:
        _restore_backup(database_path, backup_path)
        restored = _connect(database_path)
        try:
            restored_revision = _revision(restored)
            validate_render_jobs_shape(restored, typed_source=source_typed)
        finally:
            restored.close()
        if restored_revision != source_revision:
            raise ProtectedMigrationError(
                "revision action failed and backup restoration did not recover the source head"
            ) from error
        raise ProtectedMigrationError(
            "revision action failed; the database was restored from its pre-migration backup"
        ) from error

    migrated = _connect(database_path)
    try:
        current_revision = _revision(migrated)
        foreign_key_check, integrity_check = validate_render_jobs_shape(
            migrated, typed_source=target_typed
        )
    finally:
        migrated.close()
    if current_revision != target_revision:
        raise ProtectedMigrationError("protected migration did not reach its target revision")
    return ProtectedMigrationEvidence(
        database_path=str(database_path),
        backup_path=str(backup_path),
        mode=mode,
        previous_revision=source_revision,
        current_revision=current_revision,
        rebuilt=evidence.rebuilt,
        render_job_count=evidence.render_job_count,
        foreign_key_check=foreign_key_check,
        integrity_check=integrity_check,
    )
