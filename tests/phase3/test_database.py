import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from manim_workbench_api.database import configure_sqlite
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
DOMAIN_TABLES = {
    "artifacts",
    "code_versions",
    "content_plan_versions",
    "generation_attempts",
    "projects",
    "prompt_versions",
    "render_jobs",
    "users",
}


def migrate(database_url: str) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def test_initial_migration_creates_domain_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "phase3.db"
    migrate(f"sqlite:///{database_path}")

    connection = sqlite3.connect(database_path)
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert DOMAIN_TABLES <= tables

    for table in DOMAIN_TABLES - {"users"}:
        columns = {row[1]: row for row in connection.execute(f"PRAGMA table_info({table})")}
        assert columns["owner_id"][3] == 1, table


def test_sqlite_connections_enable_wal_and_foreign_keys(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'wal.db'}")
    configure_sqlite(engine)

    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


@pytest.mark.parametrize(
    "table",
    ["prompt_versions", "content_plan_versions", "code_versions"],
)
def test_version_rows_are_append_only_at_database_boundary(tmp_path: Path, table: str) -> None:
    database_path = tmp_path / "immutable.db"
    migrate(f"sqlite:///{database_path}")
    engine = create_engine(f"sqlite:///{database_path}")

    with engine.begin() as connection:
        owner_id = "00000000-0000-0000-0000-000000000001"
        project_id = "00000000-0000-0000-0000-000000000002"
        connection.execute(
            text("INSERT INTO users (id, email, created_at) VALUES (:id, :email, :created_at)"),
            {"id": owner_id, "email": "owner@example.com", "created_at": "2026-08-04T00:00:00Z"},
        )
        connection.execute(
            text(
                "INSERT INTO projects (id, owner_id, title, created_at) "
                "VALUES (:id, :owner_id, :title, :created_at)"
            ),
            {
                "id": project_id,
                "owner_id": owner_id,
                "title": "Project",
                "created_at": "2026-08-04T00:00:00Z",
            },
        )

        columns = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}
        values = {
            "id": "00000000-0000-0000-0000-000000000003",
            "project_id": project_id,
            "owner_id": owner_id,
            "version": 1,
            "parent_version_id": None,
            "created_at": "2026-08-04T00:00:00Z",
            "prompt": "Prompt",
            "schema_version": "1.0",
            "content_json": "{}",
            "prompt_version_id": "00000000-0000-0000-0000-000000000003",
            "content_plan_version_id": "00000000-0000-0000-0000-000000000003",
            "source_code": "class Scene: pass",
            "source_sha256": "a" * 64,
            "engine": "manimce",
            "engine_version": "0.20.1",
        }
        insert_columns = sorted(columns & values.keys())
        params = {name: values[name] for name in insert_columns}
        placeholders = ", ".join(f":{name}" for name in insert_columns)
        connection.execute(
            text(f"INSERT INTO {table} ({', '.join(insert_columns)}) VALUES ({placeholders})"),
            params,
        )

        with pytest.raises(Exception, match="append-only"):
            connection.execute(text(f"UPDATE {table} SET version = 2"))
