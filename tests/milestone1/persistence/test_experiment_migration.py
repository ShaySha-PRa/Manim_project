from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from manim_workbench_api.database import configure_sqlite
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parents[3]
OWNER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_OWNER_ID = UUID("00000000-0000-0000-0000-000000000002")
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000011")
OTHER_PROJECT_ID = UUID("00000000-0000-0000-0000-000000000012")
EXPERIMENT_ID = UUID("00000000-0000-0000-0000-000000000021")
SECOND_EXPERIMENT_ID = UUID("00000000-0000-0000-0000-000000000022")
MODEL_SPEC_JSON = (
    '{"domain_kind":"generic","payload":{},"plugin_id":"core.generic",'
    '"plugin_version":"1.0","schema_version":"1.0"}'
)


def migration_config(database: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    return config


def migrated_engine(tmp_path: Path) -> tuple[Config, Engine]:
    database = tmp_path / "experiments-migration.db"
    config = migration_config(database)
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}")
    configure_sqlite(engine)
    return config, engine


def seed_project(engine: Engine) -> None:
    with engine.begin() as connection:
        for owner_id, email in (
            (OWNER_ID, "owner@example.test"),
            (OTHER_OWNER_ID, "other@example.test"),
        ):
            connection.execute(
                text("INSERT INTO users (id, email, created_at) VALUES (:id, :email, :created_at)"),
                {"id": str(owner_id), "email": email, "created_at": "2026-08-10T00:00:00+00:00"},
            )
        for project_id, owner_id in (
            (PROJECT_ID, OWNER_ID),
            (OTHER_PROJECT_ID, OTHER_OWNER_ID),
        ):
            connection.execute(
                text(
                    "INSERT INTO projects (id, owner_id, title, created_at, updated_at) "
                    "VALUES (:id, :owner_id, :title, :created_at, :updated_at)"
                ),
                {
                    "id": str(project_id),
                    "owner_id": str(owner_id),
                    "title": "Migration fixture",
                    "created_at": "2026-08-10T00:00:00+00:00",
                    "updated_at": "2026-08-10T00:00:00+00:00",
                },
            )


def insert_experiment(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO experiments "
                "(id, project_id, owner_id, title, domain_kind, created_at, archived_at) "
                "VALUES (:id, :project_id, :owner_id, 'Migration experiment', 'generic', "
                ":created_at, NULL)"
            ),
            {
                "id": str(EXPERIMENT_ID),
                "project_id": str(PROJECT_ID),
                "owner_id": str(OWNER_ID),
                "created_at": "2026-08-10T00:00:00+00:00",
            },
        )


def insert_experiment_row(
    engine: Engine,
    *,
    experiment_id: UUID = EXPERIMENT_ID,
    project_id: UUID = PROJECT_ID,
    owner_id: UUID = OWNER_ID,
    domain_kind: str = "generic",
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO experiments "
                "(id, project_id, owner_id, title, domain_kind, created_at) VALUES "
                "(:id, :project_id, :owner_id, 'Constraint fixture', :domain_kind, :created_at)"
            ),
            {
                "id": str(experiment_id),
                "project_id": str(project_id),
                "owner_id": str(owner_id),
                "domain_kind": domain_kind,
                "created_at": "2026-08-10T00:00:00+00:00",
            },
        )


def version_values(
    *,
    version_id: UUID | None = None,
    experiment_id: UUID = EXPERIMENT_ID,
    project_id: UUID = PROJECT_ID,
    owner_id: UUID = OWNER_ID,
    version: int = 1,
    parent_version_id: UUID | None = None,
    draft_revision: int = 1,
    content_hash: str = "a" * 64,
) -> dict[str, object]:
    return {
        "id": str(version_id or uuid4()),
        "experiment_id": str(experiment_id),
        "project_id": str(project_id),
        "owner_id": str(owner_id),
        "version": version,
        "parent_version_id": str(parent_version_id) if parent_version_id else None,
        "draft_revision": draft_revision,
        "model_spec": MODEL_SPEC_JSON,
        "content_hash": content_hash,
        "created_at": "2026-08-10T00:00:00+00:00",
    }


def insert_version_row(engine: Engine, values: dict[str, object]) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO experiment_versions "
                "(id, experiment_id, project_id, owner_id, version, parent_version_id, "
                "draft_revision, model_spec_json, parameters_json, observables_json, "
                "assumptions_json, visualization_json, code_files_json, content_hash, created_at) "
                "VALUES (:id, :experiment_id, :project_id, :owner_id, :version, "
                ":parent_version_id, :draft_revision, :model_spec, '[]', '[]', '[]', '{}', '[]', "
                ":content_hash, :created_at)"
            ),
            values,
        )


def proposal_values(
    *,
    proposal_id: UUID | None = None,
    experiment_id: UUID = EXPERIMENT_ID,
    project_id: UUID = PROJECT_ID,
    owner_id: UUID = OWNER_ID,
    status: str = "pending",
    source: str = "model",
    resolved_at: str | None = None,
    rejection_reason: str | None = None,
) -> dict[str, object]:
    return {
        "id": str(proposal_id or uuid4()),
        "experiment_id": str(experiment_id),
        "project_id": str(project_id),
        "owner_id": str(owner_id),
        "status": status,
        "source": source,
        "resolved_at": resolved_at,
        "rejection_reason": rejection_reason,
    }


def insert_proposal_row(engine: Engine, values: dict[str, object]) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO experiment_patch_proposals "
                "(id, experiment_id, project_id, owner_id, expected_revision, status, "
                "operations_json, assumptions_json, source, created_at, resolved_at, "
                "rejection_reason) VALUES (:id, :experiment_id, :project_id, :owner_id, 1, "
                ":status, '[]', '[]', :source, '2026-08-10T00:00:00+00:00', :resolved_at, "
                ":rejection_reason)"
            ),
            values,
        )


def test_upgrade_creates_experiment_tables_constraints_and_indexes(tmp_path: Path) -> None:
    """Catches an incomplete M1 migration that omits its persistence boundary."""
    _, engine = migrated_engine(tmp_path)
    inspector = inspect(engine)

    assert {
        "experiments",
        "experiment_drafts",
        "experiment_versions",
        "experiment_patch_proposals",
    } <= set(inspector.get_table_names())
    assert {
        "id",
        "project_id",
        "owner_id",
        "title",
        "domain_kind",
        "created_at",
        "archived_at",
    } <= {column["name"] for column in inspector.get_columns("experiments")}
    assert {
        "experiment_id",
        "project_id",
        "owner_id",
        "revision",
        "model_spec_json",
        "parameters_json",
        "observables_json",
        "assumptions_json",
        "visualization_json",
        "code_files_json",
        "updated_at",
    } <= {column["name"] for column in inspector.get_columns("experiment_drafts")}
    assert {
        "id",
        "experiment_id",
        "project_id",
        "owner_id",
        "version",
        "parent_version_id",
        "draft_revision",
        "content_hash",
        "created_at",
    } <= {column["name"] for column in inspector.get_columns("experiment_versions")}
    assert {
        "id",
        "experiment_id",
        "project_id",
        "owner_id",
        "expected_revision",
        "status",
        "operations_json",
        "assumptions_json",
        "source",
        "created_at",
        "resolved_at",
        "rejection_reason",
    } <= {column["name"] for column in inspector.get_columns("experiment_patch_proposals")}
    assert {
        "ix_experiments_owner_project_id",
        "ix_experiment_drafts_owner_experiment",
        "ix_experiment_versions_owner_experiment_version",
        "ix_experiment_patch_proposals_owner_experiment_id",
    } <= {
        index["name"]
        for table in (
            "experiments",
            "experiment_drafts",
            "experiment_versions",
            "experiment_patch_proposals",
        )
        for index in inspector.get_indexes(table)
    }


def test_constraints_and_triggers_enforce_ownership_history_and_proposal_lifecycle(
    tmp_path: Path,
) -> None:
    """Catches rows that bypass M1 ownership, immutable history, or proposal transitions."""
    _, engine = migrated_engine(tmp_path)
    seed_project(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO experiments "
                    "(id, project_id, owner_id, title, domain_kind, created_at) VALUES "
                    "('00000000-0000-0000-0000-000000000099', :project_id, :owner_id, "
                    "'Wrong owner', 'generic', '2026-08-10T00:00:00+00:00')"
                ),
                {"project_id": str(PROJECT_ID), "owner_id": str(OTHER_OWNER_ID)},
            )

    insert_experiment(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO experiment_drafts "
                "(experiment_id, project_id, owner_id, revision, model_spec_json, parameters_json, "
                "observables_json, assumptions_json, visualization_json, code_files_json, "
                "updated_at) "
                "VALUES (:experiment_id, :project_id, :owner_id, 1, :model_spec, '[]', '[]', '[]', "
                "'{}', '[]', '2026-08-10T00:00:00+00:00')"
            ),
            {
                "experiment_id": str(EXPERIMENT_ID),
                "project_id": str(PROJECT_ID),
                "owner_id": str(OWNER_ID),
                "model_spec": MODEL_SPEC_JSON,
            },
        )
        connection.execute(
            text(
                "INSERT INTO experiment_versions "
                "(id, experiment_id, project_id, owner_id, version, parent_version_id, "
                "draft_revision, model_spec_json, parameters_json, observables_json, "
                "assumptions_json, visualization_json, "
                "code_files_json, content_hash, created_at) VALUES "
                "(:id, :experiment_id, :project_id, :owner_id, 1, NULL, 1, :model_spec, "
                "'[]', '[]', "
                "'[]', '{}', '[]', :hash, '2026-08-10T00:00:00+00:00')"
            ),
            {
                "id": "00000000-0000-0000-0000-000000000031",
                "experiment_id": str(EXPERIMENT_ID),
                "project_id": str(PROJECT_ID),
                "owner_id": str(OWNER_ID),
                "model_spec": MODEL_SPEC_JSON,
                "hash": "a" * 64,
            },
        )
        connection.execute(
            text(
                "INSERT INTO experiment_patch_proposals "
                "(id, experiment_id, project_id, owner_id, expected_revision, status, "
                "operations_json, "
                "assumptions_json, source, created_at, resolved_at, rejection_reason) VALUES "
                "(:id, :experiment_id, :project_id, :owner_id, 1, 'pending', '[]', '[]', 'model', "
                "'2026-08-10T00:00:00+00:00', NULL, NULL)"
            ),
            {
                "id": "00000000-0000-0000-0000-000000000041",
                "experiment_id": str(EXPERIMENT_ID),
                "project_id": str(PROJECT_ID),
                "owner_id": str(OWNER_ID),
            },
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE experiment_versions SET draft_revision = 2 WHERE version = 1")
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM experiment_versions WHERE version = 1"))
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE experiment_patch_proposals SET status = 'pending' "
                    "WHERE id = '00000000-0000-0000-0000-000000000041'"
                )
            )

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE experiment_patch_proposals SET status = 'applied', "
                "resolved_at = '2026-08-10T00:00:01+00:00' "
                "WHERE id = '00000000-0000-0000-0000-000000000041'"
            )
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE experiment_patch_proposals SET rejection_reason = 'too late' "
                    "WHERE id = '00000000-0000-0000-0000-000000000041'"
                )
            )


def test_schema_declares_composite_child_foreign_keys_named_checks_and_unique_keys(
    tmp_path: Path,
) -> None:
    """Catches removal of an ownership FK, named constraint, or version uniqueness key."""
    _, engine = migrated_engine(tmp_path)
    inspector = inspect(engine)

    expected_fk = ("experiment_id", "project_id", "owner_id")
    for table in (
        "experiment_drafts",
        "experiment_versions",
        "experiment_patch_proposals",
    ):
        foreign_keys = inspector.get_foreign_keys(table)
        ownership = next(
            foreign_key
            for foreign_key in foreign_keys
            if tuple(foreign_key["constrained_columns"]) == expected_fk
        )
        assert tuple(ownership["referred_columns"]) == ("id", "project_id", "owner_id")
        assert ownership["options"]["ondelete"] == "CASCADE"

    assert {
        "ck_experiments_domain_kind",
    } <= {check["name"] for check in inspector.get_check_constraints("experiments")}
    assert {
        "ck_experiment_versions_version",
        "ck_experiment_versions_draft_revision",
        "ck_experiment_versions_content_hash",
        "ck_experiment_versions_parent",
    } <= {check["name"] for check in inspector.get_check_constraints("experiment_versions")}
    assert {
        "ck_experiment_proposals_revision",
        "ck_experiment_proposals_status",
        "ck_experiment_proposals_source",
        "ck_experiment_proposals_lifecycle",
    } <= {
        check["name"]
        for check in inspector.get_check_constraints("experiment_patch_proposals")
    }
    assert {
        ("id", "experiment_id"),
        ("experiment_id", "version"),
        ("experiment_id", "content_hash"),
    } <= {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("experiment_versions")
    }


def test_composite_child_foreign_keys_reject_cross_experiment_ownership(tmp_path: Path) -> None:
    """Catches child rows whose project/owner pair does not belong to their experiment."""
    _, engine = migrated_engine(tmp_path)
    seed_project(engine)
    insert_experiment_row(engine)

    statements = (
        (
            "INSERT INTO experiment_drafts "
            "(experiment_id, project_id, owner_id, revision, model_spec_json, parameters_json, "
            "observables_json, assumptions_json, visualization_json, code_files_json, updated_at) "
            "VALUES (:experiment_id, :project_id, :owner_id, 1, :model_spec, '[]', '[]', '[]', "
            "'{}', '[]', '2026-08-10T00:00:00+00:00')",
            {
                "experiment_id": str(EXPERIMENT_ID),
                "project_id": str(OTHER_PROJECT_ID),
                "owner_id": str(OTHER_OWNER_ID),
                "model_spec": MODEL_SPEC_JSON,
            },
        ),
        (
            "INSERT INTO experiment_versions "
            "(id, experiment_id, project_id, owner_id, version, parent_version_id, "
            "draft_revision, model_spec_json, parameters_json, observables_json, assumptions_json, "
            "visualization_json, code_files_json, content_hash, created_at) VALUES "
            "(:id, :experiment_id, :project_id, :owner_id, 1, NULL, 1, :model_spec, '[]', "
            "'[]', '[]', '{}', '[]', :content_hash, '2026-08-10T00:00:00+00:00')",
            {
                **version_values(
                    project_id=OTHER_PROJECT_ID,
                    owner_id=OTHER_OWNER_ID,
                ),
            },
        ),
        (
            "INSERT INTO experiment_patch_proposals "
            "(id, experiment_id, project_id, owner_id, expected_revision, status, "
            "operations_json, assumptions_json, source, created_at) VALUES "
            "(:id, :experiment_id, :project_id, :owner_id, 1, 'pending', '[]', '[]', "
            "'model', '2026-08-10T00:00:00+00:00')",
            proposal_values(project_id=OTHER_PROJECT_ID, owner_id=OTHER_OWNER_ID),
        ),
    )
    for statement, parameters in statements:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text(statement), parameters)


def test_experiment_owner_update_trigger_rejects_project_owner_mismatch(tmp_path: Path) -> None:
    """Catches removal of the BEFORE UPDATE owner/project trigger."""
    _, engine = migrated_engine(tmp_path)
    seed_project(engine)
    insert_experiment_row(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE experiments SET owner_id = :owner_id WHERE id = :experiment_id"),
                {"owner_id": str(OTHER_OWNER_ID), "experiment_id": str(EXPERIMENT_ID)},
            )
    with engine.connect() as connection:
        owner_id = connection.execute(
            text("SELECT owner_id FROM experiments WHERE id = :experiment_id"),
            {"experiment_id": str(EXPERIMENT_ID)},
        ).scalar_one()
    assert owner_id == str(OWNER_ID)


@pytest.mark.parametrize(
    "domain_kind",
    [
        "generic",
        "geometry",
        "ode",
        "pde",
        "fem",
        "stochastic",
        "optimization",
        "neural_network",
        "custom_python",
    ],
)
def test_domain_constraint_accepts_every_contract_value(tmp_path: Path, domain_kind: str) -> None:
    """Catches a domain check that accidentally omits a Task 1 enum value."""
    _, engine = migrated_engine(tmp_path)
    seed_project(engine)
    insert_experiment_row(engine, domain_kind=domain_kind)


def test_domain_constraint_rejects_values_outside_the_contract(tmp_path: Path) -> None:
    """Catches removal or widening of the exact experiment domain check."""
    _, engine = migrated_engine(tmp_path)
    seed_project(engine)
    with pytest.raises(IntegrityError):
        insert_experiment_row(engine, domain_kind="not_a_domain")


@pytest.mark.parametrize("content_hash", ["a" * 63, "A" * 64, "g" * 64])
def test_version_hash_constraint_requires_lowercase_sha256(
    tmp_path: Path, content_hash: str
) -> None:
    """Catches removal or weakening of the SHA-256 format check."""
    _, engine = migrated_engine(tmp_path)
    seed_project(engine)
    insert_experiment_row(engine)
    with pytest.raises(IntegrityError):
        insert_version_row(engine, version_values(content_hash=content_hash))


def test_version_parent_and_unique_constraints_reject_invalid_history(tmp_path: Path) -> None:
    """Catches invalid roots, missing/cross-experiment parents, or duplicate version/hash rows."""
    _, engine = migrated_engine(tmp_path)
    seed_project(engine)
    insert_experiment_row(engine)
    insert_experiment_row(
        engine,
        experiment_id=SECOND_EXPERIMENT_ID,
        project_id=OTHER_PROJECT_ID,
        owner_id=OTHER_OWNER_ID,
    )
    first_id = uuid4()
    other_first_id = uuid4()
    insert_version_row(engine, version_values(version_id=first_id))
    insert_version_row(
        engine,
        version_values(
            version_id=other_first_id,
            experiment_id=SECOND_EXPERIMENT_ID,
            project_id=OTHER_PROJECT_ID,
            owner_id=OTHER_OWNER_ID,
            content_hash="b" * 64,
        ),
    )

    invalid_rows = (
        version_values(
            version_id=uuid4(),
            version=1,
            parent_version_id=first_id,
            content_hash="c" * 64,
        ),
        version_values(
            version_id=uuid4(),
            version=2,
            parent_version_id=None,
            content_hash="d" * 64,
        ),
        version_values(
            version_id=uuid4(),
            version=2,
            parent_version_id=other_first_id,
            content_hash="e" * 64,
        ),
        version_values(version_id=uuid4(), version=1, content_hash="f" * 64),
        version_values(version_id=uuid4(), version=2, parent_version_id=first_id),
    )
    for values in invalid_rows:
        with pytest.raises(IntegrityError):
            insert_version_row(engine, values)


@pytest.mark.parametrize("source", ["user", "model", "import", "system"])
def test_proposal_source_constraint_accepts_every_contract_value(
    tmp_path: Path, source: str
) -> None:
    """Catches a source check that accidentally omits a Task 1 enum value."""
    _, engine = migrated_engine(tmp_path)
    seed_project(engine)
    insert_experiment_row(engine)
    insert_proposal_row(engine, proposal_values(source=source))


@pytest.mark.parametrize(
    ("status", "resolved_at", "rejection_reason"),
    [
        ("pending", "2026-08-10T00:00:01+00:00", None),
        ("pending", None, "not pending-safe"),
        ("applied", None, None),
        ("applied", "2026-08-10T00:00:01+00:00", "not allowed"),
        ("rejected", None, "missing timestamp"),
        ("unknown", None, None),
    ],
)
def test_proposal_status_and_lifecycle_constraints_reject_invalid_rows(
    tmp_path: Path,
    status: str,
    resolved_at: str | None,
    rejection_reason: str | None,
) -> None:
    """Catches removal or weakening of proposal status/lifecycle checks."""
    _, engine = migrated_engine(tmp_path)
    seed_project(engine)
    insert_experiment_row(engine)
    with pytest.raises(IntegrityError):
        insert_proposal_row(
            engine,
            proposal_values(
                status=status,
                resolved_at=resolved_at,
                rejection_reason=rejection_reason,
            ),
        )


def test_proposal_source_constraint_rejects_unknown_source(tmp_path: Path) -> None:
    """Catches removal or widening of the exact proposal source check."""
    _, engine = migrated_engine(tmp_path)
    seed_project(engine)
    insert_experiment_row(engine)
    with pytest.raises(IntegrityError):
        insert_proposal_row(engine, proposal_values(source="assistant"))


def test_proposal_transition_trigger_rejects_content_changes_during_resolution(
    tmp_path: Path,
) -> None:
    """Catches a trigger that permits content mutation alongside pending-to-applied."""
    _, engine = migrated_engine(tmp_path)
    seed_project(engine)
    insert_experiment_row(engine)
    proposal_id = uuid4()
    insert_proposal_row(engine, proposal_values(proposal_id=proposal_id))

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE experiment_patch_proposals SET status = 'applied', "
                    "resolved_at = '2026-08-10T00:00:01+00:00', operations_json = '[{}]' "
                    "WHERE id = :proposal_id"
                ),
                {"proposal_id": str(proposal_id)},
            )
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT status, operations_json FROM experiment_patch_proposals "
                "WHERE id = :proposal_id"
            ),
            {"proposal_id": str(proposal_id)},
        ).one()
    assert tuple(row) == ("pending", "[]")


def test_downgrade_preserves_pre_0007_data_and_reupgrade_restores_m1_schema(tmp_path: Path) -> None:
    """Catches a downgrade that damages Phase 9 state or cannot be applied again."""
    database = tmp_path / "experiments-downgrade.db"
    config = migration_config(database)
    command.upgrade(config, "0006_phase9")
    engine = create_engine(f"sqlite:///{database}")
    configure_sqlite(engine)
    seed_project(engine)

    command.upgrade(config, "head")
    with engine.connect() as connection:
        title = connection.execute(
            text("SELECT title FROM projects WHERE id = :id"), {"id": str(PROJECT_ID)}
        ).scalar_one()
        assert title == "Migration fixture"

    command.downgrade(config, "0006_phase9")
    inspector = inspect(create_engine(f"sqlite:///{database}"))
    assert "experiments" not in inspector.get_table_names()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one() == 2
        assert connection.execute(text("SELECT COUNT(*) FROM projects")).scalar_one() == 2

    command.upgrade(config, "head")
    assert "experiments" in inspect(create_engine(f"sqlite:///{database}")).get_table_names()
