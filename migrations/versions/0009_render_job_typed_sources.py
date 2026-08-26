"""Validate a protected offline RenderJob typed-source rebuild."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from alembic import op
from manim_workbench_api.database_migrations.render_job_typed_sources import (
    validate_render_jobs_shape,
)

revision: str = "0009_render_job_typed_sources"
down_revision: str | None = "0008_asset_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_MESSAGE = (
    "render_jobs must be prepared with scripts/migrate_render_job_typed_sources.py "
    "before upgrading through 0009"
)
_DOWNGRADE_MESSAGE = (
    "render_jobs must be prepared with scripts/migrate_render_job_typed_sources.py "
    "before downgrading through 0009"
)


def _database() -> sqlite3.Connection:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        raise RuntimeError("RenderJob typed-source migration only supports SQLite")
    raw = getattr(bind.connection, "driver_connection", None)
    if not isinstance(raw, sqlite3.Connection):
        raise RuntimeError("could not access the SQLite driver connection")
    return raw


def upgrade() -> None:
    try:
        validate_render_jobs_shape(_database(), typed_source=True)
    except RuntimeError as error:
        raise RuntimeError(_UPGRADE_MESSAGE) from error


def downgrade() -> None:
    try:
        validate_render_jobs_shape(_database(), typed_source=False)
    except RuntimeError as error:
        raise RuntimeError(_DOWNGRADE_MESSAGE) from error
