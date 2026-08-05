from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

ROOT = Path(__file__).resolve().parents[3]


def test_0006_creates_append_only_quality_schema(tmp_path: Path) -> None:
    database = tmp_path / "phase9.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")
    inspector = inspect(create_engine(f"sqlite:///{database}"))
    assert {"quality_reports", "quality_diagnostics", "quality_ratings"} <= set(
        inspector.get_table_names()
    )
    report_columns = {column["name"] for column in inspector.get_columns("quality_reports")}
    assert {
        "owner_id",
        "target_duration_seconds",
        "estimated_duration_seconds",
        "actual_duration_seconds",
        "diagnostic_signature",
        "repair_count",
    } <= report_columns

    command.downgrade(config, "0005_phase8")
    assert (
        "quality_reports" not in inspect(create_engine(f"sqlite:///{database}")).get_table_names()
    )
