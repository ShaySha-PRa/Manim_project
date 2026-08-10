from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from manim_workbench_api.database import configure_sqlite
from manim_workbench_api.experiments.errors import ExperimentRepositoryError
from manim_workbench_api.experiments.repository import ExperimentRepository
from manim_workbench_contracts import (
    AssumptionSource,
    ExperimentCreateRequest,
    ExperimentDomainKind,
    ExperimentDraftUpdateRequest,
    ExperimentPatchOperation,
    ExperimentPatchOperationKind,
    ExperimentPatchProposalApplyRequest,
    ExperimentPatchProposalRejectRequest,
    ExperimentVersionCreateRequest,
)
from sqlalchemy import Engine, create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[3]
OWNER_ID = UUID("10000000-0000-0000-0000-000000000001")
OTHER_OWNER_ID = UUID("10000000-0000-0000-0000-000000000002")
PROJECT_ID = UUID("10000000-0000-0000-0000-000000000011")
OTHER_PROJECT_ID = UUID("10000000-0000-0000-0000-000000000012")
PROMPT_ID = UUID("10000000-0000-0000-0000-000000000021")
CONTENT_PLAN_ID = UUID("10000000-0000-0000-0000-000000000022")
CODE_VERSION_ID = UUID("10000000-0000-0000-0000-000000000023")
RENDER_JOB_ID = UUID("10000000-0000-0000-0000-000000000024")
ARTIFACT_ID = UUID("10000000-0000-0000-0000-000000000025")
SESSION_ID = UUID("10000000-0000-0000-0000-000000000026")
QUALITY_REPORT_ID = UUID("10000000-0000-0000-0000-000000000027")
QUALITY_DIAGNOSTIC_ID = UUID("10000000-0000-0000-0000-000000000028")
QUALITY_RATING_ID = UUID("10000000-0000-0000-0000-000000000029")
GENERATION_ATTEMPT_ID = UUID("10000000-0000-0000-0000-000000000030")

LEGACY_TABLES = (
    "users",
    "projects",
    "prompt_versions",
    "content_plan_versions",
    "code_versions",
    "render_jobs",
    "artifacts",
    "generation_attempts",
    "sessions",
    "login_attempts",
    "job_events",
    "code_generation_category_states",
    "quality_reports",
    "quality_diagnostics",
    "quality_ratings",
)
M1_TABLES = {
    "experiments",
    "experiment_drafts",
    "experiment_versions",
    "experiment_patch_proposals",
}
M1_INDEXES = {
    "ix_experiments_owner_project_id",
    "ix_experiment_drafts_owner_experiment",
    "ix_experiment_versions_owner_experiment_version",
    "ix_experiment_patch_proposals_owner_experiment_id",
}
M1_TRIGGERS = {
    "experiments_owner_matches_project_insert",
    "experiments_owner_matches_project_update",
    "experiment_versions_append_only_update",
    "experiment_versions_append_only_delete",
    "experiment_patch_proposals_pending_transition",
}


def migration_config(database: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    return config


def open_engine(database: Path) -> Engine:
    engine = create_engine(f"sqlite:///{database}", connect_args={"timeout": 10})
    configure_sqlite(engine)
    return engine


def sqlite_objects(engine: Engine) -> set[tuple[str, str, str, str | None]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE type IN ('index', 'trigger') AND name NOT LIKE 'sqlite_autoindex_%'"
            )
        ).all()
    return {(str(row[0]), str(row[1]), str(row[2]), row[3]) for row in rows}


def table_rows(engine: Engine, table: str) -> tuple[tuple[object, ...], ...]:
    columns = [column["name"] for column in inspect(engine).get_columns(table)]
    projection = ", ".join(columns)
    with engine.connect() as connection:
        rows = connection.execute(text(f"SELECT {projection} FROM {table} ORDER BY rowid")).all()
    return tuple(tuple(row) for row in rows)


def legacy_snapshot(engine: Engine) -> dict[str, tuple[tuple[object, ...], ...]]:
    return {table: table_rows(engine, table) for table in LEGACY_TABLES}


def seed_phase9_fixture(engine: Engine) -> None:
    timestamp = "2026-08-10T00:00:00+00:00"
    source_code = "from manim import Scene\n\nclass DemoScene(Scene):\n    pass\n"
    source_sha256 = hashlib.sha256(source_code.encode()).hexdigest()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, email, created_at, password_hash, must_change_password, "
                "password_changed_at, disabled_at) VALUES "
                "(:id, :email, :created_at, :password_hash, 0, :password_changed_at, NULL)"
            ),
            {
                "id": str(OWNER_ID),
                "email": "compat-owner@example.test",
                "created_at": timestamp,
                "password_hash": "compat-password-hash",
                "password_changed_at": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO users (id, email, created_at, password_hash, must_change_password, "
                "password_changed_at, disabled_at) VALUES "
                "(:id, :email, :created_at, :password_hash, 0, :password_changed_at, NULL)"
            ),
            {
                "id": str(OTHER_OWNER_ID),
                "email": "compat-other@example.test",
                "created_at": timestamp,
                "password_hash": "compat-password-hash-2",
                "password_changed_at": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO projects (id, owner_id, title, created_at, archived_at, updated_at) "
                "VALUES (:id, :owner_id, :title, :created_at, NULL, :updated_at)"
            ),
            {
                "id": str(PROJECT_ID),
                "owner_id": str(OWNER_ID),
                "title": "Compatibility project",
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO projects (id, owner_id, title, created_at, archived_at, updated_at) "
                "VALUES (:id, :owner_id, :title, :created_at, NULL, :updated_at)"
            ),
            {
                "id": str(OTHER_PROJECT_ID),
                "owner_id": str(OTHER_OWNER_ID),
                "title": "Other compatibility project",
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO prompt_versions "
                "(id, project_id, owner_id, version, parent_version_id, created_at, prompt) "
                "VALUES (:id, :project_id, :owner_id, 1, NULL, :created_at, :prompt)"
            ),
            {
                "id": str(PROMPT_ID),
                "project_id": str(PROJECT_ID),
                "owner_id": str(OWNER_ID),
                "created_at": timestamp,
                "prompt": "Explain a parabola vertex derivation.",
            },
        )
        connection.execute(
            text(
                "INSERT INTO content_plan_versions "
                "(id, project_id, owner_id, version, parent_version_id, created_at, "
                "schema_version, content_json) VALUES "
                "(:id, :project_id, :owner_id, 1, NULL, :created_at, '1.1', :content_json)"
            ),
            {
                "id": str(CONTENT_PLAN_ID),
                "project_id": str(PROJECT_ID),
                "owner_id": str(OWNER_ID),
                "created_at": timestamp,
                "content_json": '{"schema_version":"1.1","scenes":[]}',
            },
        )
        connection.execute(
            text(
                "INSERT INTO code_versions "
                "(id, project_id, owner_id, version, parent_version_id, created_at, "
                "prompt_version_id, content_plan_version_id, source_code, source_sha256, "
                "engine, engine_version, scene_class, category, generation_mode, "
                "prompt_template_version, provider_model, assumptions_json) VALUES "
                "(:id, :project_id, :owner_id, 1, NULL, :created_at, :prompt_version_id, "
                ":content_plan_version_id, :source_code, :source_sha256, 'manimce', '0.20.1', "
                ":scene_class, 'formula_derivation', 'full', 'phase9-v1', 'offline-fixture', '[]')"
            ),
            {
                "id": str(CODE_VERSION_ID),
                "project_id": str(PROJECT_ID),
                "owner_id": str(OWNER_ID),
                "created_at": timestamp,
                "prompt_version_id": str(PROMPT_ID),
                "content_plan_version_id": str(CONTENT_PLAN_ID),
                "source_code": source_code,
                "source_sha256": source_sha256,
                "scene_class": "DemoScene",
            },
        )
        connection.execute(
            text(
                "INSERT INTO render_jobs "
                "(id, project_id, owner_id, code_version_id, profile, status, idempotency_key, "
                "created_at, started_at, finished_at, failure_code, attempt_count, lease_owner, "
                "lease_token, lease_expires_at, heartbeat_at, cancellation_requested_at, "
                "state_version) VALUES "
                "(:id, :project_id, :owner_id, :code_version_id, 'preview', 'queued', "
                "'compatibility-idempotency-key', :created_at, NULL, NULL, NULL, 0, NULL, NULL, "
                "NULL, NULL, NULL, 0)"
            ),
            {
                "id": str(RENDER_JOB_ID),
                "project_id": str(PROJECT_ID),
                "owner_id": str(OWNER_ID),
                "code_version_id": str(CODE_VERSION_ID),
                "created_at": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO artifacts "
                "(id, project_id, owner_id, render_job_id, kind, relative_path, sha256, "
                "byte_size, created_at) VALUES "
                "(:id, :project_id, :owner_id, :render_job_id, 'video', "
                "'renders/compatibility.mp4', :sha256, 42, :created_at)"
            ),
            {
                "id": str(ARTIFACT_ID),
                "project_id": str(PROJECT_ID),
                "owner_id": str(OWNER_ID),
                "render_job_id": str(RENDER_JOB_ID),
                "sha256": "b" * 64,
                "created_at": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO generation_attempts "
                "(id, project_id, owner_id, stage, attempt_number, status, input_version_id, "
                "output_version_id, error_code, created_at, provider_request_id, provider_model, "
                "prompt_tokens, completion_tokens, candidate_sha256, diagnostic_sha256) VALUES "
                "(:id, :project_id, :owner_id, 'code_generation', 1, 'succeeded', "
                ":input_version_id, :output_version_id, NULL, :created_at, 'offline-request', "
                "'offline-fixture', 10, 20, :candidate_sha256, :diagnostic_sha256)"
            ),
            {
                "id": str(GENERATION_ATTEMPT_ID),
                "project_id": str(PROJECT_ID),
                "owner_id": str(OWNER_ID),
                "input_version_id": str(PROMPT_ID),
                "output_version_id": str(CODE_VERSION_ID),
                "created_at": timestamp,
                "candidate_sha256": source_sha256,
                "diagnostic_sha256": "c" * 64,
            },
        )
        connection.execute(
            text(
                "INSERT INTO sessions "
                "(id, user_id, token_hash, csrf_token_hash, created_at, last_seen_at, expires_at, "
                "revoked_at, user_agent_hash, remote_addr_hash) VALUES "
                "(:id, :user_id, :token_hash, :csrf_token_hash, :created_at, :last_seen_at, "
                ":expires_at, NULL, :user_agent_hash, :remote_addr_hash)"
            ),
            {
                "id": str(SESSION_ID),
                "user_id": str(OWNER_ID),
                "token_hash": "d" * 64,
                "csrf_token_hash": "e" * 64,
                "created_at": timestamp,
                "last_seen_at": timestamp,
                "expires_at": "2026-08-11T00:00:00+00:00",
                "user_agent_hash": "f" * 64,
                "remote_addr_hash": "0" * 64,
            },
        )
        connection.execute(
            text(
                "INSERT INTO login_attempts "
                "(identifier_hash, remote_addr_hash, attempted_at, succeeded) VALUES "
                "(:identifier_hash, :remote_addr_hash, :attempted_at, 1)"
            ),
            {
                "identifier_hash": "1" * 64,
                "remote_addr_hash": "2" * 64,
                "attempted_at": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO job_events "
                "(render_job_id, owner_id, state_version, stage, status, error_code, created_at) "
                "VALUES (:render_job_id, :owner_id, 1, 'preview_render', 'queued', NULL, "
                ":created_at)"
            ),
            {
                "render_job_id": str(RENDER_JOB_ID),
                "owner_id": str(OWNER_ID),
                "created_at": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO code_generation_category_states "
                "(category, status, consecutive_failed_rounds, updated_at) VALUES "
                "('formula_derivation', 'active', 0, :updated_at)"
            ),
            {"updated_at": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO quality_reports "
                "(id, project_id, owner_id, render_job_id, code_version_id, "
                "content_plan_version_id, status, target_duration_seconds, "
                "estimated_duration_seconds, actual_duration_seconds, frame_rate, frame_count, "
                "score, repair_count, diagnostic_signature, provider_model, "
                "prompt_template_version, content_plan_schema_version, manim_version, "
                "image_digest, ast_policy_version, diagnostic_policy_version, created_at) VALUES "
                "(:id, :project_id, :owner_id, :render_job_id, :code_version_id, "
                ":content_plan_version_id, 'passed', 60, 58, 59, 30, 1770, 96, 0, :signature, "
                "'offline-fixture', 'phase9-v1', '1.1', '0.20.1', :image_digest, "
                "'phase7-v1', 'phase9-visual-v1', :created_at)"
            ),
            {
                "id": str(QUALITY_REPORT_ID),
                "project_id": str(PROJECT_ID),
                "owner_id": str(OWNER_ID),
                "render_job_id": str(RENDER_JOB_ID),
                "code_version_id": str(CODE_VERSION_ID),
                "content_plan_version_id": str(CONTENT_PLAN_ID),
                "signature": "a" * 64,
                "image_digest": "sha256:" + "b" * 64,
                "created_at": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO quality_diagnostics "
                "(id, quality_report_id, owner_id, code, severity, stage, message, suggestion, "
                "evidence_ref, measured_value, threshold_value, created_at) VALUES "
                "(:id, :quality_report_id, :owner_id, 'static_blank', 'info', 'preview_render', "
                "'No blocking issue', 'Keep the current layout.', 'frame-0001', 0, 1, :created_at)"
            ),
            {
                "id": str(QUALITY_DIAGNOSTIC_ID),
                "quality_report_id": str(QUALITY_REPORT_ID),
                "owner_id": str(OWNER_ID),
                "created_at": timestamp,
            },
        )
        connection.execute(
            text(
                "INSERT INTO quality_ratings "
                "(id, quality_report_id, owner_id, score, notes, created_at) VALUES "
                "(:id, :quality_report_id, :owner_id, 5, 'Useful compatibility fixture', "
                ":created_at)"
            ),
            {
                "id": str(QUALITY_RATING_ID),
                "quality_report_id": str(QUALITY_REPORT_ID),
                "owner_id": str(OWNER_ID),
                "created_at": timestamp,
            },
        )


def operation(kind: ExperimentPatchOperationKind, path: str, value=...):  # type: ignore[no-untyped-def]
    values = {"operation": kind, "path": path}
    if value is not ...:
        values["value"] = value
    return ExperimentPatchOperation(**values)


def test_empty_database_upgrade_creates_only_the_four_m1_tables(tmp_path: Path) -> None:
    database = tmp_path / "empty.db"
    command.upgrade(migration_config(database), "head")
    engine = open_engine(database)
    try:
        tables = set(inspect(engine).get_table_names())
        assert M1_TABLES <= tables
        assert tables - set(LEGACY_TABLES) - {"alembic_version"} == M1_TABLES
        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert version == "0007_experiment_core"
    finally:
        engine.dispose()


def test_0006_0007_downgrade_reupgrade_preserves_legacy_rows_and_public_experiment_lifecycle(
    tmp_path: Path,
) -> None:
    database = tmp_path / "compatibility.db"
    config = migration_config(database)
    command.upgrade(config, "0006_phase9")
    engine = open_engine(database)
    try:
        seed_phase9_fixture(engine)
        before_upgrade = legacy_snapshot(engine)
        objects_at_0006 = sqlite_objects(engine)

        command.upgrade(config, "head")
        assert legacy_snapshot(engine) == before_upgrade
        repository = ExperimentRepository(engine)
        experiment, initial = repository.create_experiment(
            PROJECT_ID,
            OWNER_ID,
            ExperimentCreateRequest(
                title="Post-migration experiment", domain_kind=ExperimentDomainKind.PDE
            ),
        )
        assert initial.revision == 1
        assert repository.get_experiment(experiment.id, OWNER_ID) == experiment

        updated = repository.update_draft(
            experiment.id,
            OWNER_ID,
            ExperimentDraftUpdateRequest(expected_revision=1, visualization={"seed": True}),
        )
        with pytest.raises(ExperimentRepositoryError) as stale:
            repository.update_draft(
                experiment.id,
                OWNER_ID,
                ExperimentDraftUpdateRequest(expected_revision=1, visualization={"stale": True}),
            )
        assert stale.value.code == "experiment_revision_conflict"

        version, created = repository.create_version(
            experiment.id,
            OWNER_ID,
            ExperimentVersionCreateRequest(expected_revision=updated.revision),
        )
        repeated, repeated_created = repository.create_version(
            experiment.id,
            OWNER_ID,
            ExperimentVersionCreateRequest(expected_revision=updated.revision),
        )
        assert created is True
        assert repeated_created is False
        assert repeated.id == version.id
        with pytest.raises(ExperimentRepositoryError) as hidden:
            repository.get_experiment(experiment.id, OTHER_OWNER_ID)
        assert hidden.value.code == "experiment_not_found"

        applied_proposal = repository.create_patch_proposal(
            experiment.id,
            OWNER_ID,
            updated.revision,
            (operation(ExperimentPatchOperationKind.ADD, "/visualization/compat", True),),
            (),
            AssumptionSource.MODEL,
        )
        applied = repository.apply_patch_proposal(
            experiment.id,
            applied_proposal.id,
            OWNER_ID,
            ExperimentPatchProposalApplyRequest(expected_revision=updated.revision),
        )
        assert applied.revision == updated.revision + 1

        invalid_proposal = repository.create_patch_proposal(
            experiment.id,
            OWNER_ID,
            applied.revision,
            (operation(ExperimentPatchOperationKind.REPLACE, "/visualization/missing", 1),),
            (),
            AssumptionSource.MODEL,
        )
        with pytest.raises(ExperimentRepositoryError) as invalid:
            repository.apply_patch_proposal(
                experiment.id,
                invalid_proposal.id,
                OWNER_ID,
                ExperimentPatchProposalApplyRequest(expected_revision=applied.revision),
            )
        assert invalid.value.code == "experiment_patch_invalid"
        rejected_proposal = repository.create_patch_proposal(
            experiment.id,
            OWNER_ID,
            applied.revision,
            (operation(ExperimentPatchOperationKind.ADD, "/visualization/rejected", True),),
            (),
            AssumptionSource.MODEL,
        )
        rejected = repository.reject_patch_proposal(
            experiment.id,
            rejected_proposal.id,
            OWNER_ID,
            ExperimentPatchProposalRejectRequest(
                expected_revision=applied.revision, reason="Compatibility fixture"
            ),
        )
        assert rejected.status.value == "rejected"
        with pytest.raises(ExperimentRepositoryError) as hidden_version:
            repository.list_versions(experiment.id, OTHER_OWNER_ID, cursor=None, limit=20)
        assert hidden_version.value.code == "experiment_not_found"

        command.downgrade(config, "0006_phase9")
        assert sqlite_objects(engine) == objects_at_0006
        tables_after_downgrade = set(inspect(engine).get_table_names())
        assert not M1_TABLES & tables_after_downgrade
        with engine.connect() as connection:
            names = {
                str(row[0])
                for row in connection.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type IN ('index', 'trigger') "
                    "AND name NOT LIKE 'sqlite_autoindex_%'"
                )
                )
            }
        assert not (M1_INDEXES | M1_TRIGGERS) & names
        assert legacy_snapshot(engine) == before_upgrade

        command.upgrade(config, "head")
        assert M1_TABLES <= set(inspect(engine).get_table_names())
        assert legacy_snapshot(engine) == before_upgrade
    finally:
        engine.dispose()
