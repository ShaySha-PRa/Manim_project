"""Add Phase 7 code-generation provenance and category policy state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_phase7"
down_revision: str | None = "0003_phase6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_code_version_triggers() -> None:
    op.execute("DROP TRIGGER IF EXISTS code_versions_prevent_delete")
    op.execute("DROP TRIGGER IF EXISTS code_versions_prevent_update")


def _create_code_version_triggers() -> None:
    op.execute(
        "CREATE TRIGGER code_versions_prevent_update BEFORE UPDATE ON code_versions "
        "BEGIN SELECT RAISE(ABORT, 'code_versions is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER code_versions_prevent_delete BEFORE DELETE ON code_versions "
        "BEGIN SELECT RAISE(ABORT, 'code_versions is append-only'); END"
    )


def upgrade() -> None:
    _drop_code_version_triggers()
    with op.batch_alter_table("code_versions") as batch:
        batch.add_column(
            sa.Column(
                "category",
                sa.String(40),
                nullable=False,
                server_default="formula_derivation",
            )
        )
        batch.add_column(
            sa.Column("generation_mode", sa.String(40), nullable=False, server_default="full")
        )
        batch.add_column(sa.Column("prompt_template_version", sa.String(100), nullable=True))
        batch.add_column(sa.Column("provider_model", sa.String(100), nullable=True))
        batch.add_column(
            sa.Column("assumptions_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch.create_check_constraint(
            "ck_code_versions_category",
            "category IN ('formula_derivation', 'function_visualization')",
        )
        batch.create_check_constraint(
            "ck_code_versions_generation_mode",
            "generation_mode IN ('full', 'deterministic_template')",
        )
    _create_code_version_triggers()

    with op.batch_alter_table("generation_attempts") as batch:
        batch.add_column(sa.Column("candidate_sha256", sa.String(64), nullable=True))
        batch.add_column(sa.Column("diagnostic_sha256", sa.String(64), nullable=True))

    op.create_table(
        "code_generation_category_states",
        sa.Column("category", sa.String(40), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("consecutive_failed_rounds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.String(35), nullable=False),
        sa.CheckConstraint(
            "category IN ('formula_derivation', 'function_visualization')",
            name="ck_code_generation_category_state_category",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'degraded', 'paused')",
            name="ck_code_generation_category_state_status",
        ),
        sa.CheckConstraint(
            "consecutive_failed_rounds >= 0",
            name="ck_code_generation_category_state_failed_rounds",
        ),
    )


def downgrade() -> None:
    op.drop_table("code_generation_category_states")

    with op.batch_alter_table("generation_attempts") as batch:
        batch.drop_column("diagnostic_sha256")
        batch.drop_column("candidate_sha256")

    _drop_code_version_triggers()
    with op.batch_alter_table("code_versions") as batch:
        batch.drop_constraint("ck_code_versions_generation_mode", type_="check")
        batch.drop_constraint("ck_code_versions_category", type_="check")
        batch.drop_column("assumptions_json")
        batch.drop_column("provider_model")
        batch.drop_column("prompt_template_version")
        batch.drop_column("generation_mode")
        batch.drop_column("category")
    _create_code_version_triggers()
