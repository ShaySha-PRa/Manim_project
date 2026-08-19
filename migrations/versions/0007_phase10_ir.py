"""Add Scene IR storage, 0.21.0 engine pin, concat jobs, and user assets."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_phase10_ir"
down_revision: str | None = "0006_phase9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IR_CATEGORIES = (
    "formula_derivation",
    "function_visualization",
    "plane_geometry",
    "geometry_proof",
    "three_d",
    "mixed",
)


def _create_code_version_triggers() -> None:
    op.execute("DROP TRIGGER IF EXISTS code_versions_prevent_delete")
    op.execute("DROP TRIGGER IF EXISTS code_versions_prevent_update")
    op.execute(
        "CREATE TRIGGER code_versions_prevent_update BEFORE UPDATE ON code_versions "
        "BEGIN SELECT RAISE(ABORT, 'code_versions is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER code_versions_prevent_delete BEFORE DELETE ON code_versions "
        "BEGIN SELECT RAISE(ABORT, 'code_versions is append-only'); END"
    )


def _create_render_job_event_triggers() -> None:
    op.execute("DROP TRIGGER IF EXISTS render_jobs_phase8_event_after_insert")
    op.execute("DROP TRIGGER IF EXISTS render_jobs_phase8_event_after_update")
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


def upgrade() -> None:
    with op.batch_alter_table("code_versions") as batch_op:
        batch_op.drop_constraint("ck_code_versions_engine_version", type_="check")
        batch_op.create_check_constraint(
            "ck_code_versions_engine_version",
            "engine_version IN ('0.20.1', '0.21.0')",
        )
        batch_op.drop_constraint("ck_code_versions_category", type_="check")
        batch_op.create_check_constraint(
            "ck_code_versions_category",
            "category IN (" + ", ".join(f"'{item}'" for item in _IR_CATEGORIES) + ")",
        )
        batch_op.drop_constraint("ck_code_versions_generation_mode", type_="check")
        batch_op.create_check_constraint(
            "ck_code_versions_generation_mode",
            "generation_mode IN ('full', 'deterministic_template', 'compiled_ir')",
        )
    _create_code_version_triggers()
    with op.batch_alter_table("render_jobs") as batch_op:
        batch_op.add_column(sa.Column("concat_group_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("segment_index", sa.Integer(), nullable=True))
    _create_render_job_event_triggers()
    with op.batch_alter_table("code_generation_category_states") as batch_op:
        batch_op.drop_constraint("ck_code_generation_category_state_category", type_="check")
        batch_op.create_check_constraint(
            "ck_code_generation_category_state_category",
            "category IN (" + ", ".join(f"'{item}'" for item in _IR_CATEGORIES) + ")",
        )
    op.create_table(
        "user_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("original_filename", sa.String(200), nullable=False),
        sa.Column("relative_path", sa.String(500), nullable=False),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.CheckConstraint("byte_size BETWEEN 1 AND 8000000", name="ck_user_assets_size"),
        sa.CheckConstraint(
            "kind IN ('image', 'construction_json')",
            name="ck_user_assets_kind",
        ),
        sa.UniqueConstraint("owner_id", "project_id", "sha256", name="uq_user_assets_digest"),
    )
    op.create_index(
        "ix_user_assets_owner_project",
        "user_assets",
        ["owner_id", "project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_assets_owner_project", table_name="user_assets")
    op.drop_table("user_assets")
    with op.batch_alter_table("code_generation_category_states") as batch_op:
        batch_op.drop_constraint("ck_code_generation_category_state_category", type_="check")
        batch_op.create_check_constraint(
            "ck_code_generation_category_state_category",
            "category IN ('formula_derivation', 'function_visualization')",
        )
    with op.batch_alter_table("render_jobs") as batch_op:
        batch_op.drop_column("segment_index")
        batch_op.drop_column("concat_group_id")
    _create_render_job_event_triggers()
    with op.batch_alter_table("code_versions") as batch_op:
        batch_op.drop_constraint("ck_code_versions_engine_version", type_="check")
        batch_op.create_check_constraint(
            "ck_code_versions_engine_version",
            "engine_version = '0.20.1'",
        )
        batch_op.drop_constraint("ck_code_versions_category", type_="check")
        batch_op.create_check_constraint(
            "ck_code_versions_category",
            "category IN ('formula_derivation', 'function_visualization')",
        )
        batch_op.drop_constraint("ck_code_versions_generation_mode", type_="check")
        batch_op.create_check_constraint(
            "ck_code_versions_generation_mode",
            "generation_mode IN ('full', 'deterministic_template')",
        )
    _create_code_version_triggers()
