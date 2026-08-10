from __future__ import annotations

from pathlib import Path
from uuid import UUID

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
