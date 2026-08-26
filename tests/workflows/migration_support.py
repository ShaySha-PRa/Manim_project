from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from manim_workbench_api.database_migrations.protected_render_job_migration import (
    run_protected_migration,
)

ROOT = Path(__file__).resolve().parents[2]


def upgrade_workflow_database(database_path: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0008_asset_versions")
    run_protected_migration(
        database_path=database_path,
        backup_path=database_path.with_name(f"{database_path.name}.pre-0009.backup"),
        alembic_config_path=ROOT / "alembic.ini",
        mode="upgrade",
        services_stopped=True,
    )
    command.upgrade(config, "0010_video_workflows")
    return config
