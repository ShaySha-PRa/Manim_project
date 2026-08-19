from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from manim_workbench_api.assets.scientific import ingest_csv_text
from manim_workbench_api.assets.versions import load_asset_version, persist_asset_version
from manim_workbench_api.tools.registry import invoke
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


def test_asset_versions_table_is_append_only(tmp_path: Path) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    db = tmp_path / "assets.db"
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db}")
    csv = ingest_csv_text("time,temperature,pressure\n1,2,3\n")
    persist_asset_version(engine, csv)
    loaded = load_asset_version(engine, csv.sha256)
    assert loaded is not None
    assert loaded.columns == csv.columns
    invoke(
        "wave2d_superposition",
        {"nx": 8, "ny": 8, "nt": 4},
        output_root=tmp_path,
        engine=engine,
    )
    with engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM asset_versions")).scalar_one()
    assert count >= 2
    with pytest.raises(IntegrityError, match="append-only"):
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM asset_versions"))
