"""Add durable, owner-scoped workflow Director planning history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_workflow_director"
down_revision: str | None = "0010_video_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _protect_append_only(table: str) -> None:
    op.execute(
        f"CREATE TRIGGER {table}_prevent_update BEFORE UPDATE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
    )
    op.execute(
        f"CREATE TRIGGER {table}_prevent_delete BEFORE DELETE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
    )


def upgrade() -> None:
    with op.batch_alter_table("workflow_tasks") as batch_op:
        batch_op.drop_constraint("ck_workflow_tasks_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_workflow_tasks_kind",
            "kind IN ('scene_program','composition','director_plan')",
        )

    op.create_table(
        "workflow_director_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("draft_json", sa.Text(), nullable=True),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("output_sha256", sa.String(64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_model", sa.String(100), nullable=True),
        sa.Column("prompt_template_version", sa.String(100), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.Column("updated_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "status IN ('queued','planning','ready','needs_confirmation','failed','cancelled')",
            name="ck_director_plan_status",
        ),
        sa.CheckConstraint("json_valid(request_json)", name="ck_director_request_json"),
        sa.CheckConstraint(
            "draft_json IS NULL OR json_valid(draft_json)", name="ck_director_draft_json"
        ),
        sa.CheckConstraint("length(cache_key) = 64", name="ck_director_cache_key"),
        sa.CheckConstraint("length(input_sha256) = 64", name="ck_director_input_hash"),
        sa.CheckConstraint(
            "output_sha256 IS NULL OR length(output_sha256) = 64",
            name="ck_director_output_hash",
        ),
        sa.CheckConstraint("attempt_count BETWEEN 0 AND 2", name="ck_director_attempts"),
        sa.CheckConstraint("state_version >= 0", name="ck_director_state"),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_director_idempotency"),
        sa.UniqueConstraint(
            "owner_id", "project_id", "cache_key", name="uq_director_scope_cache"
        ),
    )
    op.create_index(
        "ix_director_plans_owner_project",
        "workflow_director_plans",
        ["owner_id", "project_id", "created_at"],
    )

    op.create_table(
        "workflow_director_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plan_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider_model", sa.String(100), nullable=True),
        sa.Column("provider_request_id", sa.String(200), nullable=True),
        sa.Column("prompt_template_version", sa.String(100), nullable=False),
        sa.Column("prompt_sha256", sa.String(64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("candidate_sha256", sa.String(64), nullable=True),
        sa.Column("diagnostic_sha256", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["workflow_director_plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("attempt_number BETWEEN 1 AND 2"),
        sa.CheckConstraint("status IN ('started','succeeded','failed')"),
        sa.CheckConstraint("length(prompt_sha256) = 64"),
        sa.CheckConstraint("candidate_sha256 IS NULL OR length(candidate_sha256) = 64"),
        sa.CheckConstraint("diagnostic_sha256 IS NULL OR length(diagnostic_sha256) = 64"),
        sa.UniqueConstraint("plan_id", "attempt_number"),
    )
    op.create_index(
        "ix_director_attempts_owner_plan",
        "workflow_director_attempts",
        ["owner_id", "plan_id", "attempt_number"],
    )

    op.create_table(
        "workflow_director_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plan_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["workflow_director_plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("state_version >= 0"),
        sa.CheckConstraint(
            "status IN ('queued','planning','ready','needs_confirmation','failed','cancelled')"
        ),
        sa.UniqueConstraint("plan_id", "state_version"),
    )
    op.create_index(
        "ix_director_events_owner_plan",
        "workflow_director_events",
        ["owner_id", "plan_id", "state_version"],
    )
    _protect_append_only("workflow_director_attempts")
    _protect_append_only("workflow_director_events")
    op.execute(
        """
        CREATE TRIGGER workflow_director_events_enforce_state_version
        BEFORE INSERT ON workflow_director_events
        BEGIN
          SELECT CASE
            WHEN NEW.state_version != COALESCE(
              (SELECT MAX(state_version) + 1 FROM workflow_director_events
               WHERE plan_id = NEW.plan_id),
              0
            )
            THEN RAISE(ABORT, 'workflow_director_events state_version must be monotonic')
          END;
        END
        """
    )
    op.execute(
        "CREATE TRIGGER workflow_director_plans_prevent_delete "
        "BEFORE DELETE ON workflow_director_plans "
        "BEGIN SELECT RAISE(ABORT, 'workflow_director_plans cannot be deleted'); END"
    )

    op.add_column(
        "video_workflow_versions", sa.Column("director_plan_id", sa.String(36), nullable=True)
    )
    op.add_column(
        "video_workflow_versions", sa.Column("director_edits_json", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.exec_driver_sql(
        "SELECT COUNT(*) FROM workflow_tasks WHERE kind='director_plan'"
    ).scalar_one():
        raise RuntimeError("cannot downgrade workflow Director while tasks exist")
    if connection.exec_driver_sql(
        "SELECT COUNT(*) FROM workflow_director_plans"
    ).scalar_one():
        raise RuntimeError("cannot downgrade workflow Director while plan history exists")
    if connection.exec_driver_sql(
        "SELECT COUNT(*) FROM video_workflow_versions WHERE director_plan_id IS NOT NULL"
    ).scalar_one():
        raise RuntimeError("cannot downgrade workflow Director provenance")

    op.drop_column("video_workflow_versions", "director_edits_json")
    op.drop_column("video_workflow_versions", "director_plan_id")
    op.drop_index("ix_director_events_owner_plan", table_name="workflow_director_events")
    op.drop_table("workflow_director_events")
    op.drop_index("ix_director_attempts_owner_plan", table_name="workflow_director_attempts")
    op.drop_table("workflow_director_attempts")
    op.drop_index("ix_director_plans_owner_project", table_name="workflow_director_plans")
    op.drop_table("workflow_director_plans")
    with op.batch_alter_table("workflow_tasks") as batch_op:
        batch_op.drop_constraint("ck_workflow_tasks_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_workflow_tasks_kind", "kind IN ('scene_program','composition')"
        )
