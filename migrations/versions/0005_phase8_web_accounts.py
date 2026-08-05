"""Add Phase 8 browser accounts, durable sessions and job events."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_phase8"
down_revision: str | None = "0004_phase7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("password_hash", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default="1")
        )
        batch.add_column(sa.Column("password_changed_at", sa.String(35), nullable=True))
        batch.add_column(sa.Column("disabled_at", sa.String(35), nullable=True))

    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("updated_at", sa.String(35), nullable=True))

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.Column("last_seen_at", sa.String(35), nullable=False),
        sa.Column("expires_at", sa.String(35), nullable=False),
        sa.Column("revoked_at", sa.String(35), nullable=True),
        sa.Column("user_agent_hash", sa.String(64), nullable=True),
        sa.Column("remote_addr_hash", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_sessions_user_active", "sessions", ["user_id", "expires_at"])

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("identifier_hash", sa.String(64), nullable=False),
        sa.Column("remote_addr_hash", sa.String(64), nullable=False),
        sa.Column("attempted_at", sa.String(35), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "ix_login_attempts_window",
        "login_attempts",
        ["identifier_hash", "remote_addr_hash", "attempted_at"],
    )

    op.create_table(
        "job_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("render_job_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["render_job_id"], ["render_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.UniqueConstraint("render_job_id", "state_version", name="uq_job_events_state"),
        sa.CheckConstraint("state_version >= 0", name="ck_job_events_state_version"),
        sa.CheckConstraint(
            "stage IN ('prompt', 'content_plan', 'code_generation', "
            "'preview_render', 'final_render', 'artifact_delivery')",
            name="ck_job_events_stage",
        ),
    )
    op.create_index("ix_job_events_owner_id", "job_events", ["owner_id", "id"])
    op.execute(
        """
        CREATE TRIGGER render_jobs_phase8_event_after_insert
        AFTER INSERT ON render_jobs
        BEGIN
          INSERT INTO job_events (
            render_job_id, owner_id, state_version, stage, status, error_code, created_at
          ) VALUES (
            NEW.id, NEW.owner_id, NEW.state_version,
            CASE NEW.profile WHEN 'preview' THEN 'preview_render' ELSE 'final_render' END,
            NEW.status, NEW.failure_code, NEW.created_at
          );
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER render_jobs_phase8_event_after_update
        AFTER UPDATE ON render_jobs
        WHEN NEW.state_version != OLD.state_version
          AND (NEW.status != OLD.status
               OR NEW.cancellation_requested_at IS NOT OLD.cancellation_requested_at)
        BEGIN
          INSERT INTO job_events (
            render_job_id, owner_id, state_version, stage, status, error_code, created_at
          ) VALUES (
            NEW.id, NEW.owner_id, NEW.state_version,
            CASE NEW.profile WHEN 'preview' THEN 'preview_render' ELSE 'final_render' END,
            NEW.status, NEW.failure_code, COALESCE(NEW.finished_at, NEW.started_at, NEW.created_at)
          );
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS render_jobs_phase8_event_after_update")
    op.execute("DROP TRIGGER IF EXISTS render_jobs_phase8_event_after_insert")
    op.drop_index("ix_job_events_owner_id", table_name="job_events")
    op.drop_table("job_events")
    op.drop_index("ix_login_attempts_window", table_name="login_attempts")
    op.drop_table("login_attempts")
    op.drop_index("ix_sessions_user_active", table_name="sessions")
    op.drop_table("sessions")

    with op.batch_alter_table("projects") as batch:
        batch.drop_column("updated_at")

    with op.batch_alter_table("users") as batch:
        batch.drop_column("disabled_at")
        batch.drop_column("password_changed_at")
        batch.drop_column("must_change_password")
        batch.drop_column("password_hash")
