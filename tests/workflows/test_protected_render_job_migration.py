from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from manim_workbench_api.database_migrations.protected_render_job_migration import (
    ProtectedMigrationError,
    run_protected_migration,
)
from manim_workbench_api.database_migrations.render_job_typed_sources import (
    rebuild_render_jobs,
)

from tests.workflows.test_render_job_shadow_migration import _0008_database

ROOT = Path(__file__).resolve().parents[2]


def _config(database_path: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return config


def _state(database_path: Path) -> tuple[str, tuple[str, ...], list[tuple[object, ...]]]:
    database = sqlite3.connect(database_path)
    try:
        revision = str(database.execute("SELECT version_num FROM alembic_version").fetchone()[0])
        columns = tuple(
            str(row[1]) for row in database.execute("PRAGMA table_info(render_jobs)")
        )
        jobs = database.execute("SELECT * FROM render_jobs ORDER BY id").fetchall()
        return revision, columns, jobs
    finally:
        database.close()


def test_plain_alembic_rejects_unprepared_0008(tmp_path: Path) -> None:
    database_path = _0008_database(tmp_path)
    before = _state(database_path)

    with pytest.raises(RuntimeError, match="migrate_render_job_typed_sources.py"):
        command.upgrade(_config(database_path), "0009_render_job_typed_sources")

    assert _state(database_path) == before


def test_protected_upgrade_requires_stopped_services_and_fresh_backup(tmp_path: Path) -> None:
    database_path = _0008_database(tmp_path)
    backup_path = tmp_path / "guarded.backup.db"
    before = _state(database_path)

    with pytest.raises(ProtectedMigrationError, match="API and Runner are stopped"):
        run_protected_migration(
            database_path=database_path,
            backup_path=backup_path,
            alembic_config_path=ROOT / "alembic.ini",
            mode="upgrade",
            services_stopped=False,
        )
    assert _state(database_path) == before
    assert not backup_path.exists()

    backup_path.write_bytes(b"do-not-overwrite")
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        run_protected_migration(
            database_path=database_path,
            backup_path=backup_path,
            alembic_config_path=ROOT / "alembic.ini",
            mode="upgrade",
            services_stopped=True,
        )
    assert backup_path.read_bytes() == b"do-not-overwrite"
    assert _state(database_path) == before


def test_protected_upgrade_marks_0009_then_0010_retries_normally(tmp_path: Path) -> None:
    database_path = _0008_database(tmp_path)
    backup_path = tmp_path / "protected-upgrade.backup.db"

    evidence = run_protected_migration(
        database_path=database_path,
        backup_path=backup_path,
        alembic_config_path=ROOT / "alembic.ini",
        mode="upgrade",
        services_stopped=True,
    )

    revision, columns, _ = _state(database_path)
    assert evidence.rebuilt is True
    assert evidence.current_revision == revision == "0009_render_job_typed_sources"
    assert "program_render_segment_id" in columns
    assert backup_path.is_file()
    command.upgrade(_config(database_path), "0010_video_workflows")
    assert _state(database_path)[0] == "0010_video_workflows"


def test_revision_failure_restores_complete_0008_backup(tmp_path: Path) -> None:
    database_path = _0008_database(tmp_path)
    backup_path = tmp_path / "revision-failure.backup.db"
    before = _state(database_path)

    def stamp_then_fail(config: Config, target: str) -> None:
        command.upgrade(config, target)
        raise RuntimeError("injected failure after revision mark")

    with pytest.raises(ProtectedMigrationError, match="restored"):
        run_protected_migration(
            database_path=database_path,
            backup_path=backup_path,
            alembic_config_path=ROOT / "alembic.ini",
            mode="upgrade",
            services_stopped=True,
            revision_action=stamp_then_fail,
        )

    assert _state(database_path) == before
    assert backup_path.is_file()


def test_prepared_intermediate_schema_resumes_without_rebuild(tmp_path: Path) -> None:
    database_path = _0008_database(tmp_path)
    backup_path = tmp_path / "resume.backup.db"
    database = sqlite3.connect(database_path, isolation_level=None)
    try:
        first = rebuild_render_jobs(database, backup_path, typed_source=True)
    finally:
        database.close()
    assert first.rebuilt is True

    evidence = run_protected_migration(
        database_path=database_path,
        backup_path=backup_path,
        alembic_config_path=ROOT / "alembic.ini",
        mode="upgrade",
        services_stopped=True,
    )

    assert evidence.rebuilt is False
    assert _state(database_path)[0] == "0009_render_job_typed_sources"


def test_protected_downgrade_refuses_scientific_job_before_backup(tmp_path: Path) -> None:
    database_path = _0008_database(tmp_path)
    upgrade_backup = tmp_path / "science-upgrade.backup.db"
    run_protected_migration(
        database_path=database_path,
        backup_path=upgrade_backup,
        alembic_config_path=ROOT / "alembic.ini",
        mode="upgrade",
        services_stopped=True,
    )
    database = sqlite3.connect(database_path, isolation_level=None)
    try:
        database.execute("PRAGMA foreign_keys=ON")
        database.execute(
            "INSERT INTO render_jobs "
            "(id,project_id,owner_id,code_version_id,program_render_segment_id,profile,"
            "status,idempotency_key,created_at) VALUES "
            "('50000000-0000-0000-0000-000000000099',"
            "'10000000-0000-0000-0000-000000000001',"
            "'00000000-0000-0000-0000-000000000001',NULL,"
            "'80000000-0000-0000-0000-000000000001','preview','queued',"
            "'scientific-protected-job','2026-08-24T00:00:00+00:00')"
        )
    finally:
        database.close()
    before = _state(database_path)
    downgrade_backup = tmp_path / "science-downgrade.backup.db"

    with pytest.raises(RuntimeError, match="cannot downgrade"):
        run_protected_migration(
            database_path=database_path,
            backup_path=downgrade_backup,
            alembic_config_path=ROOT / "alembic.ini",
            mode="downgrade",
            services_stopped=True,
        )

    assert _state(database_path) == before
    assert not downgrade_backup.exists()
