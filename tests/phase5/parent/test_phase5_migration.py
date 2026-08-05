import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[3]


def test_phase5_migration_adds_durable_lease_and_recovery_state(tmp_path: Path) -> None:
    database_path = tmp_path / "phase5.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")

    connection = sqlite3.connect(database_path)
    columns = {
        row[1]: row for row in connection.execute("PRAGMA table_info(render_jobs)")
    }
    assert {
        "attempt_count",
        "lease_owner",
        "lease_token",
        "lease_expires_at",
        "heartbeat_at",
        "cancellation_requested_at",
        "state_version",
    } <= columns.keys()
    assert columns["attempt_count"][3] == 1
    assert columns["state_version"][3] == 1
    indexes = {
        row[1] for row in connection.execute("PRAGMA index_list(render_jobs)")
    }
    assert "ix_render_jobs_recovery" in indexes
    code_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(code_versions)")
    }
    assert "scene_class" in code_columns


def test_phase5_migration_downgrades_to_phase3_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "phase5-downgrade.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    command.downgrade(config, "0001_phase3")

    connection = sqlite3.connect(database_path)
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(render_jobs)")
    }
    assert "attempt_count" not in columns
    assert "lease_token" not in columns
    assert "state_version" not in columns
    code_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(code_versions)")
    }
    assert "scene_class" not in code_columns
