"""Add append-only scientific AssetVersion provenance table."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_asset_versions"
down_revision: str | None = "0007_phase10_ir"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MIME = (
    "text/csv",
    "application/x-npy",
    "application/x-npz",
    "text/plain",
    "application/pdf",
)


def upgrade() -> None:
    op.create_table(
        "asset_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("mime", sa.String(40), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("derived_from", sa.String(64), nullable=True),
        sa.Column("columns_json", sa.Text(), nullable=False),
        sa.Column("fields_json", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=True),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.CheckConstraint("size_bytes BETWEEN 1 AND 64000000", name="ck_asset_versions_size"),
        sa.CheckConstraint("source IN ('upload', 'tool_output')", name="ck_asset_versions_source"),
        sa.CheckConstraint(
            "mime IN (" + ", ".join(f"'{item}'" for item in _MIME) + ")",
            name="ck_asset_versions_mime",
        ),
        sa.UniqueConstraint("sha256", name="uq_asset_versions_sha256"),
    )
    op.create_index("ix_asset_versions_created", "asset_versions", ["created_at"])
    op.execute(
        "CREATE TRIGGER asset_versions_prevent_update BEFORE UPDATE ON asset_versions "
        "BEGIN SELECT RAISE(ABORT, 'asset_versions is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER asset_versions_prevent_delete BEFORE DELETE ON asset_versions "
        "BEGIN SELECT RAISE(ABORT, 'asset_versions is append-only'); END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS asset_versions_prevent_update")
    op.execute("DROP TRIGGER IF EXISTS asset_versions_prevent_delete")
    op.drop_index("ix_asset_versions_created", table_name="asset_versions")
    op.drop_table("asset_versions")
