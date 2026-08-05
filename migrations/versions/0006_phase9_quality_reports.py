"""Add append-only Phase 9 quality reports, diagnostics and ratings."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_phase9"
down_revision: str | None = "0005_phase8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _append_only(table: str) -> None:
    for action in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only_{action.lower()} "
            f"BEFORE {action} ON {table} BEGIN "
            "SELECT RAISE(ABORT, 'quality history is append-only'); END"
        )


def upgrade() -> None:
    op.create_table(
        "quality_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("render_job_id", sa.String(36), nullable=False),
        sa.Column("code_version_id", sa.String(36), nullable=False),
        sa.Column("content_plan_version_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("target_duration_seconds", sa.Float(), nullable=False),
        sa.Column("estimated_duration_seconds", sa.Float(), nullable=True),
        sa.Column("actual_duration_seconds", sa.Float(), nullable=True),
        sa.Column("frame_rate", sa.Float(), nullable=True),
        sa.Column("frame_count", sa.Integer(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("repair_count", sa.Integer(), nullable=False),
        sa.Column("diagnostic_signature", sa.String(64), nullable=False),
        sa.Column("provider_model", sa.String(100), nullable=False),
        sa.Column("prompt_template_version", sa.String(100), nullable=False),
        sa.Column("content_plan_schema_version", sa.String(20), nullable=False),
        sa.Column("manim_version", sa.String(50), nullable=False),
        sa.Column("image_digest", sa.String(71), nullable=False),
        sa.Column("ast_policy_version", sa.String(100), nullable=False),
        sa.Column("diagnostic_policy_version", sa.String(100), nullable=False),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["render_job_id"], ["render_jobs.id"]),
        sa.ForeignKeyConstraint(["code_version_id"], ["code_versions.id"]),
        sa.ForeignKeyConstraint(["content_plan_version_id"], ["content_plan_versions.id"]),
        sa.CheckConstraint("repair_count BETWEEN 0 AND 2", name="ck_quality_repair_count"),
        sa.CheckConstraint("score IS NULL OR score BETWEEN 0 AND 100", name="ck_quality_score"),
    )
    op.create_index(
        "ix_quality_reports_owner_project",
        "quality_reports",
        ["owner_id", "project_id", "created_at"],
    )
    op.create_index("ix_quality_reports_job", "quality_reports", ["render_job_id", "created_at"])

    op.create_table(
        "quality_diagnostics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("quality_report_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=False),
        sa.Column("evidence_ref", sa.String(500), nullable=True),
        sa.Column("measured_value", sa.Float(), nullable=True),
        sa.Column("threshold_value", sa.Float(), nullable=True),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["quality_report_id"], ["quality_reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
    )
    op.create_index(
        "ix_quality_diagnostics_report",
        "quality_diagnostics",
        ["quality_report_id", "id"],
    )

    op.create_table(
        "quality_ratings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("quality_report_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["quality_report_id"], ["quality_reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.CheckConstraint("score BETWEEN 0 AND 100", name="ck_quality_rating_score"),
    )
    op.create_index(
        "ix_quality_ratings_report",
        "quality_ratings",
        ["quality_report_id", "created_at"],
    )
    for table in ("quality_reports", "quality_diagnostics", "quality_ratings"):
        _append_only(table)


def downgrade() -> None:
    for table in ("quality_ratings", "quality_diagnostics", "quality_reports"):
        for action in ("delete", "update"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only_{action}")
    op.drop_index("ix_quality_ratings_report", table_name="quality_ratings")
    op.drop_table("quality_ratings")
    op.drop_index("ix_quality_diagnostics_report", table_name="quality_diagnostics")
    op.drop_table("quality_diagnostics")
    op.drop_index("ix_quality_reports_job", table_name="quality_reports")
    op.drop_index("ix_quality_reports_owner_project", table_name="quality_reports")
    op.drop_table("quality_reports")
