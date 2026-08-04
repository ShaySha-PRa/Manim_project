"""Add durable Phase 5 render-job lease and cancellation state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase5"
down_revision: str | None = "0001_phase3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("render_jobs") as batch:
        batch.add_column(
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("lease_owner", sa.String(100), nullable=True))
        batch.add_column(sa.Column("lease_token", sa.String(64), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.String(35), nullable=True))
        batch.add_column(sa.Column("heartbeat_at", sa.String(35), nullable=True))
        batch.add_column(sa.Column("cancellation_requested_at", sa.String(35), nullable=True))
        batch.add_column(
            sa.Column("state_version", sa.Integer(), nullable=False, server_default="0")
        )
        batch.create_check_constraint("ck_render_jobs_attempt_count", "attempt_count >= 0")
        batch.create_check_constraint("ck_render_jobs_state_version", "state_version >= 0")
        batch.create_index(
            "ix_render_jobs_recovery", ["status", "lease_expires_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("render_jobs") as batch:
        batch.drop_index("ix_render_jobs_recovery")
        batch.drop_constraint("ck_render_jobs_state_version", type_="check")
        batch.drop_constraint("ck_render_jobs_attempt_count", type_="check")
        batch.drop_column("state_version")
        batch.drop_column("cancellation_requested_at")
        batch.drop_column("heartbeat_at")
        batch.drop_column("lease_expires_at")
        batch.drop_column("lease_token")
        batch.drop_column("lease_owner")
        batch.drop_column("attempt_count")
