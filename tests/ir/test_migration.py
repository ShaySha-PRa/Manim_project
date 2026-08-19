from pathlib import Path

from alembic import command
from alembic.config import Config


def test_phase10_migration_adds_assets_and_allows_021(tmp_path: Path) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    db = tmp_path / "ir.db"
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    command.upgrade(config, "head")
    import sqlite3

    connection = sqlite3.connect(db)
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "user_assets" in tables
    columns = {row[1] for row in connection.execute("PRAGMA table_info(render_jobs)")}
    assert {"concat_group_id", "segment_index"} <= columns
