"""Create the Phase 3 domain schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_phase3"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERSION_TABLES = ("prompt_versions", "content_plan_versions", "code_versions")


def identity_columns(include_project: bool = True) -> list[sa.Column]:
    columns = [sa.Column("id", sa.String(36), primary_key=True)]
    if include_project:
        columns.extend(
            [
                sa.Column("project_id", sa.String(36), nullable=False),
                sa.Column("owner_id", sa.String(36), nullable=False),
            ]
        )
    return columns


def version_columns() -> list[sa.Column]:
    return [
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.String(35), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("created_at", sa.String(35), nullable=False),
    )
    op.create_table(
        "projects",
        *identity_columns(include_project=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.Column("archived_at", sa.String(35), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
    )
    op.create_table(
        "prompt_versions",
        *identity_columns(),
        *version_columns(),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["parent_version_id"], ["prompt_versions.id"]),
        sa.UniqueConstraint("project_id", "version", name="uq_prompt_versions_project_version"),
        sa.CheckConstraint("version >= 1", name="ck_prompt_versions_positive_version"),
    )
    op.create_table(
        "content_plan_versions",
        *identity_columns(),
        *version_columns(),
        sa.Column("schema_version", sa.String(10), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["parent_version_id"], ["content_plan_versions.id"]),
        sa.UniqueConstraint(
            "project_id", "version", name="uq_content_plan_versions_project_version"
        ),
        sa.CheckConstraint("version >= 1", name="ck_content_plan_versions_positive_version"),
        sa.CheckConstraint("schema_version = '1.0'", name="ck_content_plan_schema_version"),
    )
    op.create_table(
        "code_versions",
        *identity_columns(),
        *version_columns(),
        sa.Column("prompt_version_id", sa.String(36), nullable=False),
        sa.Column("content_plan_version_id", sa.String(36), nullable=False),
        sa.Column("source_code", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("engine", sa.String(20), nullable=False),
        sa.Column("engine_version", sa.String(20), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["parent_version_id"], ["code_versions.id"]),
        sa.ForeignKeyConstraint(["prompt_version_id"], ["prompt_versions.id"]),
        sa.ForeignKeyConstraint(["content_plan_version_id"], ["content_plan_versions.id"]),
        sa.UniqueConstraint("project_id", "version", name="uq_code_versions_project_version"),
        sa.CheckConstraint("version >= 1", name="ck_code_versions_positive_version"),
        sa.CheckConstraint("engine = 'manimce'", name="ck_code_versions_engine"),
        sa.CheckConstraint("engine_version = '0.20.1'", name="ck_code_versions_engine_version"),
    )
    op.create_table(
        "render_jobs",
        *identity_columns(),
        sa.Column("code_version_id", sa.String(36), nullable=False),
        sa.Column("profile", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.Column("started_at", sa.String(35), nullable=True),
        sa.Column("finished_at", sa.String(35), nullable=True),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["code_version_id"], ["code_versions.id"]),
    )
    op.create_table(
        "artifacts",
        *identity_columns(),
        sa.Column("render_job_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("relative_path", sa.String(500), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["render_job_id"], ["render_jobs.id"]),
        sa.CheckConstraint("byte_size >= 0", name="ck_artifacts_nonnegative_size"),
    )
    op.create_table(
        "generation_attempts",
        *identity_columns(),
        sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("input_version_id", sa.String(36), nullable=False),
        sa.Column("output_version_id", sa.String(36), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.CheckConstraint(
            "attempt_number BETWEEN 1 AND 3", name="ck_generation_attempts_attempt_number"
        ),
    )

    for table in VERSION_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_prevent_update BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
        )
        op.execute(
            f"CREATE TRIGGER {table}_prevent_delete BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
        )


def downgrade() -> None:
    for table in reversed(VERSION_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_prevent_delete")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_prevent_update")
    for table in (
        "generation_attempts",
        "artifacts",
        "render_jobs",
        "code_versions",
        "content_plan_versions",
        "prompt_versions",
        "projects",
        "users",
    ):
        op.drop_table(table)
