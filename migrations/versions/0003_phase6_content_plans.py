"""Add Phase 6 ContentPlan 1.1 and redacted provider-attempt metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_phase6"
down_revision: str | None = "0002_phase5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_content_plan_triggers() -> None:
    op.execute("DROP TRIGGER IF EXISTS content_plan_versions_prevent_delete")
    op.execute("DROP TRIGGER IF EXISTS content_plan_versions_prevent_update")


def _create_content_plan_triggers() -> None:
    op.execute(
        "CREATE TRIGGER content_plan_versions_prevent_update "
        "BEFORE UPDATE ON content_plan_versions "
        "BEGIN SELECT RAISE(ABORT, 'content_plan_versions is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER content_plan_versions_prevent_delete "
        "BEFORE DELETE ON content_plan_versions "
        "BEGIN SELECT RAISE(ABORT, 'content_plan_versions is append-only'); END"
    )


def upgrade() -> None:
    _drop_content_plan_triggers()
    with op.batch_alter_table("content_plan_versions") as batch:
        batch.drop_constraint("ck_content_plan_schema_version", type_="check")
        batch.create_check_constraint(
            "ck_content_plan_schema_version", "schema_version IN ('1.0', '1.1')"
        )
    _create_content_plan_triggers()

    with op.batch_alter_table("generation_attempts") as batch:
        batch.add_column(sa.Column("provider_request_id", sa.String(200), nullable=True))
        batch.add_column(sa.Column("provider_model", sa.String(100), nullable=True))
        batch.add_column(sa.Column("prompt_tokens", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("completion_tokens", sa.Integer(), nullable=True))
        batch.create_check_constraint(
            "ck_generation_attempts_prompt_tokens", "prompt_tokens IS NULL OR prompt_tokens >= 0"
        )
        batch.create_check_constraint(
            "ck_generation_attempts_completion_tokens",
            "completion_tokens IS NULL OR completion_tokens >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("generation_attempts") as batch:
        batch.drop_constraint("ck_generation_attempts_completion_tokens", type_="check")
        batch.drop_constraint("ck_generation_attempts_prompt_tokens", type_="check")
        batch.drop_column("completion_tokens")
        batch.drop_column("prompt_tokens")
        batch.drop_column("provider_model")
        batch.drop_column("provider_request_id")

    _drop_content_plan_triggers()
    with op.batch_alter_table("content_plan_versions") as batch:
        batch.drop_constraint("ck_content_plan_schema_version", type_="check")
        batch.create_check_constraint(
            "ck_content_plan_schema_version", "schema_version = '1.0'"
        )
    _create_content_plan_triggers()
