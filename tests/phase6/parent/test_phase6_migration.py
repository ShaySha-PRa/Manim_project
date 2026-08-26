import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[3]


def alembic_config(database_path: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return config


def test_phase6_migration_accepts_1_1_and_adds_redacted_usage(tmp_path: Path) -> None:
    database_path = tmp_path / "phase6.db"
    config = alembic_config(database_path)
    command.upgrade(config, "0003_phase6")

    connection = sqlite3.connect(database_path)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(generation_attempts)")}
    assert {
        "provider_request_id",
        "provider_model",
        "prompt_tokens",
        "completion_tokens",
    } <= columns
    content_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='content_plan_versions'"
    ).fetchone()[0]
    assert "'1.0', '1.1'" in content_sql


def test_phase6_migration_downgrades_to_phase5(tmp_path: Path) -> None:
    database_path = tmp_path / "phase6-downgrade.db"
    config = alembic_config(database_path)
    command.upgrade(config, "0003_phase6")
    command.downgrade(config, "0002_phase5")

    connection = sqlite3.connect(database_path)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(generation_attempts)")}
    assert "provider_request_id" not in columns
    content_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='content_plan_versions'"
    ).fetchone()[0]
    assert "schema_version = '1.0'" in content_sql
