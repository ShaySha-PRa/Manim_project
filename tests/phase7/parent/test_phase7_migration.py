import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[3]


def alembic_config(database_path: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return config


def columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def test_phase7_migration_adds_provenance_attempt_hashes_and_category_state(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "phase7.db"
    config = alembic_config(database_path)
    command.upgrade(config, "head")

    connection = sqlite3.connect(database_path)
    assert {
        "category",
        "generation_mode",
        "prompt_template_version",
        "provider_model",
        "assumptions_json",
    } <= columns(connection, "code_versions")
    assert {"candidate_sha256", "diagnostic_sha256"} <= columns(connection, "generation_attempts")
    assert "code_generation_category_states" in {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def test_phase7_migration_downgrades_to_phase6(tmp_path: Path) -> None:
    database_path = tmp_path / "phase7-downgrade.db"
    config = alembic_config(database_path)
    command.upgrade(config, "head")
    command.downgrade(config, "0003_phase6")

    connection = sqlite3.connect(database_path)
    assert "category" not in columns(connection, "code_versions")
    assert "candidate_sha256" not in columns(connection, "generation_attempts")
    assert "code_generation_category_states" not in {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
