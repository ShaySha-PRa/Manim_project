"""Add durable M1 experiment core persistence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_experiment_core"
down_revision: str | None = "0006_phase9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DOMAIN_KINDS = (
    "generic",
    "geometry",
    "ode",
    "pde",
    "fem",
    "stochastic",
    "optimization",
    "neural_network",
    "custom_python",
)
_PROPOSAL_STATUSES = ("pending", "applied", "rejected")
_ASSUMPTION_SOURCES = ("user", "model", "import", "system")


def _append_only(table: str) -> None:
    for action in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only_{action.lower()} "
            f"BEFORE {action} ON {table} BEGIN "
            "SELECT RAISE(ABORT, 'experiment history is append-only'); END"
        )


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "experiments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("domain_kind", sa.String(40), nullable=False),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.Column("archived_at", sa.String(35), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.UniqueConstraint("id", "project_id", "owner_id", name="uq_experiments_id_project_owner"),
        sa.CheckConstraint(
            f"domain_kind IN ({_sql_values(_DOMAIN_KINDS)})",
            name="ck_experiments_domain_kind",
        ),
    )
    op.create_index(
        "ix_experiments_owner_project_id",
        "experiments",
        ["owner_id", "project_id", "id"],
    )
    op.execute(
        "CREATE TRIGGER experiments_owner_matches_project_insert "
        "BEFORE INSERT ON experiments FOR EACH ROW "
        "WHEN NOT EXISTS (SELECT 1 FROM projects "
        "WHERE id = NEW.project_id AND owner_id = NEW.owner_id) "
        "BEGIN SELECT RAISE(ABORT, 'experiment project owner mismatch'); END"
    )
    op.execute(
        "CREATE TRIGGER experiments_owner_matches_project_update "
        "BEFORE UPDATE ON experiments FOR EACH ROW "
        "WHEN NOT EXISTS (SELECT 1 FROM projects "
        "WHERE id = NEW.project_id AND owner_id = NEW.owner_id) "
        "BEGIN SELECT RAISE(ABORT, 'experiment project owner mismatch'); END"
    )

    op.create_table(
        "experiment_drafts",
        sa.Column("experiment_id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("model_spec_json", sa.Text(), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("observables_json", sa.Text(), nullable=False),
        sa.Column("assumptions_json", sa.Text(), nullable=False),
        sa.Column("visualization_json", sa.Text(), nullable=False),
        sa.Column("code_files_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id", "project_id", "owner_id"],
            ["experiments.id", "experiments.project_id", "experiments.owner_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_experiment_drafts_revision"),
    )
    op.create_index(
        "ix_experiment_drafts_owner_experiment",
        "experiment_drafts",
        ["owner_id", "experiment_id"],
    )

    op.create_table(
        "experiment_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experiment_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.String(36), nullable=True),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("model_spec_json", sa.Text(), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("observables_json", sa.Text(), nullable=False),
        sa.Column("assumptions_json", sa.Text(), nullable=False),
        sa.Column("visualization_json", sa.Text(), nullable=False),
        sa.Column("code_files_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id", "project_id", "owner_id"],
            ["experiments.id", "experiments.project_id", "experiments.owner_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id", "experiment_id"],
            ["experiment_versions.id", "experiment_versions.experiment_id"],
        ),
        sa.UniqueConstraint("id", "experiment_id", name="uq_experiment_versions_id_experiment"),
        sa.UniqueConstraint(
            "experiment_id", "version", name="uq_experiment_versions_experiment_version"
        ),
        sa.UniqueConstraint(
            "experiment_id",
            "content_hash",
            name="uq_experiment_versions_experiment_content_hash",
        ),
        sa.CheckConstraint("version >= 1", name="ck_experiment_versions_version"),
        sa.CheckConstraint("draft_revision >= 1", name="ck_experiment_versions_draft_revision"),
        sa.CheckConstraint(
            "length(content_hash) = 64 AND content_hash NOT GLOB '*[^0-9a-f]*'",
            name="ck_experiment_versions_content_hash",
        ),
        sa.CheckConstraint(
            "(version = 1 AND parent_version_id IS NULL) "
            "OR (version > 1 AND parent_version_id IS NOT NULL)",
            name="ck_experiment_versions_parent",
        ),
    )
    op.create_index(
        "ix_experiment_versions_owner_experiment_version",
        "experiment_versions",
        ["owner_id", "experiment_id", "version"],
    )
    _append_only("experiment_versions")

    op.create_table(
        "experiment_patch_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experiment_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("operations_json", sa.Text(), nullable=False),
        sa.Column("assumptions_json", sa.Text(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("created_at", sa.String(35), nullable=False),
        sa.Column("resolved_at", sa.String(35), nullable=True),
        sa.Column("rejection_reason", sa.String(2_000), nullable=True),
        sa.ForeignKeyConstraint(
            ["experiment_id", "project_id", "owner_id"],
            ["experiments.id", "experiments.project_id", "experiments.owner_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("expected_revision >= 1", name="ck_experiment_proposals_revision"),
        sa.CheckConstraint(
            f"status IN ({_sql_values(_PROPOSAL_STATUSES)})",
            name="ck_experiment_proposals_status",
        ),
        sa.CheckConstraint(
            f"source IN ({_sql_values(_ASSUMPTION_SOURCES)})",
            name="ck_experiment_proposals_source",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND resolved_at IS NULL AND rejection_reason IS NULL) "
            "OR (status = 'applied' AND resolved_at IS NOT NULL AND rejection_reason IS NULL) "
            "OR (status = 'rejected' AND resolved_at IS NOT NULL)",
            name="ck_experiment_proposals_lifecycle",
        ),
    )
    op.create_index(
        "ix_experiment_patch_proposals_owner_experiment_id",
        "experiment_patch_proposals",
        ["owner_id", "experiment_id", "id"],
    )
    op.execute(
        "CREATE TRIGGER experiment_patch_proposals_pending_transition "
        "BEFORE UPDATE ON experiment_patch_proposals FOR EACH ROW "
        "WHEN NOT ("
        "OLD.id IS NEW.id AND "
        "OLD.experiment_id IS NEW.experiment_id AND "
        "OLD.project_id IS NEW.project_id AND "
        "OLD.owner_id IS NEW.owner_id AND "
        "OLD.expected_revision IS NEW.expected_revision AND "
        "OLD.operations_json IS NEW.operations_json AND "
        "OLD.assumptions_json IS NEW.assumptions_json AND "
        "OLD.source IS NEW.source AND "
        "OLD.created_at IS NEW.created_at AND "
        "OLD.status = 'pending' AND NEW.status IN ('applied', 'rejected')"
        ") BEGIN SELECT RAISE(ABORT, 'experiment proposal transition invalid'); END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS experiment_patch_proposals_pending_transition")
    for action in ("delete", "update"):
        op.execute(f"DROP TRIGGER IF EXISTS experiment_versions_append_only_{action}")
    op.execute("DROP TRIGGER IF EXISTS experiments_owner_matches_project_update")
    op.execute("DROP TRIGGER IF EXISTS experiments_owner_matches_project_insert")

    op.drop_index(
        "ix_experiment_patch_proposals_owner_experiment_id",
        table_name="experiment_patch_proposals",
    )
    op.drop_table("experiment_patch_proposals")
    op.drop_index(
        "ix_experiment_versions_owner_experiment_version",
        table_name="experiment_versions",
    )
    op.drop_table("experiment_versions")
    op.drop_index("ix_experiment_drafts_owner_experiment", table_name="experiment_drafts")
    op.drop_table("experiment_drafts")
    op.drop_index("ix_experiments_owner_project_id", table_name="experiments")
    op.drop_table("experiments")
