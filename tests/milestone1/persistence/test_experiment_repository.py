from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
from types import MappingProxyType
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from manim_workbench_api.database import configure_sqlite
from manim_workbench_contracts import (
    AssumptionSource,
    AssumptionStatus,
    ExperimentAssumption,
    ExperimentCodeFile,
    ExperimentCreateRequest,
    ExperimentDomainKind,
    ExperimentDraftUpdateRequest,
    ExperimentObservable,
    ExperimentParameter,
    ExperimentPatchOperation,
    ExperimentPatchOperationKind,
    ExperimentPatchProposalApplyRequest,
    ExperimentPatchProposalRejectRequest,
    ExperimentVersionCreateRequest,
    ModelSpec,
)
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

try:
    from manim_workbench_api.experiments import errors as experiment_errors
    from manim_workbench_api.experiments.errors import ExperimentRepositoryError
    from manim_workbench_api.experiments.repository import ExperimentRepository
except ModuleNotFoundError:
    experiment_errors = None
    ExperimentRepository = None  # type: ignore[assignment,misc]
    ExperimentRepositoryError = RuntimeError  # type: ignore[assignment,misc]

ROOT = Path(__file__).resolve().parents[3]
OWNER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_OWNER_ID = UUID("00000000-0000-0000-0000-000000000002")
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000011")
OTHER_PROJECT_ID = UUID("00000000-0000-0000-0000-000000000012")


def migrated_engine(tmp_path: Path) -> Engine:
    database = tmp_path / "experiments-repository.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}", connect_args={"timeout": 10})
    configure_sqlite(engine)
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
                    "title": "Repository fixture",
                    "created_at": "2026-08-10T00:00:00+00:00",
                    "updated_at": "2026-08-10T00:00:00+00:00",
                },
            )
    return engine


def repository_type():  # type: ignore[no-untyped-def]
    assert ExperimentRepository is not None, (
        "ExperimentRepository must be implemented for M1 persistence"
    )
    return ExperimentRepository


def make_repository(tmp_path: Path):  # type: ignore[no-untyped-def]
    return repository_type()(migrated_engine(tmp_path))


def create_experiment(repository):  # type: ignore[no-untyped-def]
    return repository.create_experiment(
        PROJECT_ID,
        OWNER_ID,
        ExperimentCreateRequest(title="Heat equation", domain_kind=ExperimentDomainKind.ODE),
    )


def assert_error(action, code: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ExperimentRepositoryError) as caught:
        action()
    assert caught.value.code == code


def test_repository_public_surface_and_frozen_error_codes_exist() -> None:
    """Catches a missing persistence API or errors whose public codes can change."""
    assert repository_type().__name__ == "ExperimentRepository"
    assert experiment_errors is not None
    assert {
        experiment_errors.PROJECT_NOT_FOUND.code,
        experiment_errors.EXPERIMENT_NOT_FOUND.code,
        experiment_errors.EXPERIMENT_PROPOSAL_NOT_FOUND.code,
        experiment_errors.EXPERIMENT_REVISION_CONFLICT.code,
        experiment_errors.EXPERIMENT_PROPOSAL_RESOLVED.code,
        experiment_errors.EXPERIMENT_PATCH_INVALID.code,
    } == {
        "project_not_found",
        "experiment_not_found",
        "experiment_proposal_not_found",
        "experiment_revision_conflict",
        "experiment_proposal_resolved",
        "experiment_patch_invalid",
    }
    with pytest.raises((AttributeError, TypeError)):
        experiment_errors.PROJECT_NOT_FOUND.code = "changed"


def test_create_experiment_atomically_creates_the_initial_owner_scoped_draft(
    tmp_path: Path,
) -> None:
    """Catches experiment creation that leaves no revision-one draft or wrong generic plugin."""
    engine = migrated_engine(tmp_path)
    repository = repository_type()(engine)

    experiment, draft = create_experiment(repository)

    assert experiment.project_id == PROJECT_ID
    assert experiment.owner_id == OWNER_ID
    assert experiment.title == "Heat equation"
    assert draft.experiment_id == experiment.id
    assert draft.revision == 1
    assert draft.model_spec.domain_kind is ExperimentDomainKind.ODE
    assert draft.model_spec.plugin_id == "core.generic"
    assert draft.model_spec.plugin_version == "1.0"
    assert draft.model_spec.payload == {}
    assert draft.parameters == draft.observables == draft.assumptions == draft.code_files == ()
    assert draft.visualization == {}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM experiment_drafts")).scalar_one() == 1

    assert_error(
        lambda: repository.create_experiment(
            PROJECT_ID,
            OTHER_OWNER_ID,
            ExperimentCreateRequest(title="Hidden project"),
        ),
        "project_not_found",
    )


def test_experiment_reads_and_uuid_pagination_are_owner_scoped(tmp_path: Path) -> None:
    """Catches list cursor mistakes or cross-owner reads that expose experiment state."""
    repository = make_repository(tmp_path)
    created = [create_experiment(repository)[0] for _ in range(3)]
    ordered = sorted(created, key=lambda item: str(item.id))

    first = repository.list_experiments(PROJECT_ID, OWNER_ID, cursor=None, limit=2)
    second = repository.list_experiments(PROJECT_ID, OWNER_ID, cursor=first.next_cursor, limit=2)

    assert list(first.items) == ordered[:2]
    assert first.next_cursor == ordered[1].id
    assert list(second.items) == ordered[2:]
    assert second.next_cursor is None
    assert repository.get_experiment(ordered[0].id, OWNER_ID) == ordered[0]
    assert repository.get_draft(ordered[0].id, OWNER_ID).experiment_id == ordered[0].id
    assert_error(
        lambda: repository.get_experiment(ordered[0].id, OTHER_OWNER_ID), "experiment_not_found"
    )
    assert_error(
        lambda: repository.get_draft(ordered[0].id, OTHER_OWNER_ID), "experiment_not_found"
    )


def test_update_draft_preserves_omitted_values_replaces_explicit_empty_values_and_uses_cas(
    tmp_path: Path,
) -> None:
    """Catches accidental field clearing, ignored empty replacements, or stale draft writes."""
    repository = make_repository(tmp_path)
    experiment, initial = create_experiment(repository)
    updated = repository.update_draft(
        experiment.id,
        OWNER_ID,
        ExperimentDraftUpdateRequest(expected_revision=1, visualization={"series": [1, 2]}),
    )
    emptied = repository.update_draft(
        experiment.id,
        OWNER_ID,
        ExperimentDraftUpdateRequest(
            expected_revision=2,
            parameters=(),
            observables=(),
            assumptions=(),
            visualization={},
            code_files=(),
        ),
    )

    assert updated.revision == 2
    assert updated.model_spec == initial.model_spec
    assert updated.model_dump(mode="json")["visualization"] == {"series": [1, 2]}
    assert emptied.revision == 3
    assert emptied.visualization == {}
    assert emptied.parameters == emptied.observables == ()
    assert emptied.assumptions == emptied.code_files == ()
    assert_error(
        lambda: repository.update_draft(
            experiment.id,
            OWNER_ID,
            ExperimentDraftUpdateRequest(expected_revision=2, visualization={"lost": True}),
        ),
        "experiment_revision_conflict",
    )
    assert repository.get_draft(experiment.id, OWNER_ID) == emptied
    assert_error(
        lambda: repository.update_draft(
            experiment.id,
            OTHER_OWNER_ID,
            ExperimentDraftUpdateRequest(expected_revision=3, visualization={}),
        ),
        "experiment_not_found",
    )


def test_create_version_is_canonical_idempotent_and_paginates_by_descending_version(
    tmp_path: Path,
) -> None:
    """Catches duplicate snapshots, incorrect parent chains, or a non-canonical snapshot hash."""
    repository = make_repository(tmp_path)
    experiment, draft = create_experiment(repository)
    first, first_created = repository.create_version(
        experiment.id, OWNER_ID, ExperimentVersionCreateRequest(expected_revision=draft.revision)
    )
    repeated, repeated_created = repository.create_version(
        experiment.id, OWNER_ID, ExperimentVersionCreateRequest(expected_revision=draft.revision)
    )
    changed = repository.update_draft(
        experiment.id,
        OWNER_ID,
        ExperimentDraftUpdateRequest(expected_revision=1, visualization={"order": [2, 1]}),
    )
    second, second_created = repository.create_version(
        experiment.id, OWNER_ID, ExperimentVersionCreateRequest(expected_revision=changed.revision)
    )
    snapshot = {
        "model_spec": changed.model_spec.model_dump(mode="json"),
        "parameters": [],
        "observables": [],
        "assumptions": [],
        "visualization": {"order": [2, 1]},
        "code_files": [],
    }
    expected_hash = hashlib.sha256(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()

    assert first_created is True
    assert repeated_created is False
    assert repeated == first
    assert first.version == 1 and first.parent_version_id is None
    assert second_created is True
    assert second.version == 2 and second.parent_version_id == first.id
    assert second.content_hash == expected_hash
    page = repository.list_versions(experiment.id, OWNER_ID, cursor=None, limit=1)
    assert page.items == (second,)
    assert page.next_cursor == 2
    assert repository.list_versions(experiment.id, OWNER_ID, cursor=2, limit=1).items == (first,)
    assert_error(
        lambda: repository.create_version(
            experiment.id, OWNER_ID, ExperimentVersionCreateRequest(expected_revision=1)
        ),
        "experiment_revision_conflict",
    )


def test_concurrent_same_snapshot_returns_one_new_version_and_one_idempotent_result(
    tmp_path: Path,
) -> None:
    """Catches races that either duplicate a snapshot or reject an equivalent concurrent write."""
    engine = migrated_engine(tmp_path)
    repository = repository_type()(engine)
    experiment, _ = create_experiment(repository)
    barrier = Barrier(2)

    def create() -> tuple[object, bool]:
        barrier.wait()
        return repository.create_version(
            experiment.id, OWNER_ID, ExperimentVersionCreateRequest(expected_revision=1)
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: create(), range(2)))

    assert {created for _, created in results} == {False, True}
    assert len({item.id for item, _ in results}) == 1


@pytest.mark.parametrize("limit", [0, -2, 101])
def test_all_list_methods_reject_limits_outside_one_to_one_hundred(
    tmp_path: Path, limit: int
) -> None:
    """Catches unbounded, zero, or negative list queries at every repository boundary."""
    repository = make_repository(tmp_path)
    experiment, _ = create_experiment(repository)
    actions = (
        lambda: repository.list_experiments(PROJECT_ID, OWNER_ID, cursor=None, limit=limit),
        lambda: repository.list_versions(experiment.id, OWNER_ID, cursor=None, limit=limit),
        lambda: repository.list_patch_proposals(
            experiment.id, OWNER_ID, cursor=None, limit=limit
        ),
    )
    for action in actions:
        with pytest.raises(ValueError, match=r"^limit must be between 1 and 100$"):
            action()


def test_snapshot_collision_recovery_uses_original_hash_after_draft_advances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches collision recovery that incorrectly re-hashes a newer draft."""
    engine = migrated_engine(tmp_path)
    repository = repository_type()(engine)
    experiment, _ = create_experiment(repository)
    original_insert = repository_type()._insert_version
    attempted_hash: list[str] = []

    def insert_then_advance_and_collide(connection, record, snapshot) -> None:  # type: ignore[no-untyped-def]
        attempted_hash.append(record.content_hash)
        original_insert(connection, record, snapshot)
        connection.execute(
            text(
                "UPDATE experiment_drafts SET revision = revision + 1, "
                "visualization_json = :visualization_json "
                "WHERE experiment_id = :experiment_id"
            ),
            {
                "experiment_id": str(experiment.id),
                "visualization_json": '{"advanced":true}',
            },
        )
        connection.commit()
        raise IntegrityError("forced unique collision", {}, RuntimeError("collision"))

    monkeypatch.setattr(repository, "_insert_version", insert_then_advance_and_collide)

    recovered, created = repository.create_version(
        experiment.id,
        OWNER_ID,
        ExperimentVersionCreateRequest(expected_revision=1),
    )

    assert created is False
    assert recovered.content_hash == attempted_hash[0]
    assert repository.get_draft(experiment.id, OWNER_ID).revision == 2


def test_snapshot_collision_with_different_hash_is_revision_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches treating a different-hash unique collision as idempotent success."""
    engine = migrated_engine(tmp_path)
    repository = repository_type()(engine)
    experiment, _ = create_experiment(repository)
    original_insert = repository_type()._insert_version
    competing_hash = "f" * 64

    def insert_different_and_collide(connection, record, snapshot) -> None:  # type: ignore[no-untyped-def]
        competing = record.model_copy(update={"id": uuid4(), "content_hash": competing_hash})
        original_insert(connection, competing, snapshot)
        connection.commit()
        raise IntegrityError("forced unique collision", {}, RuntimeError("collision"))

    monkeypatch.setattr(repository, "_insert_version", insert_different_and_collide)

    assert_error(
        lambda: repository.create_version(
            experiment.id,
            OWNER_ID,
            ExperimentVersionCreateRequest(expected_revision=1),
        ),
        "experiment_revision_conflict",
    )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT content_hash FROM experiment_versions")
        ).scalar_one() == competing_hash


def proposal(repository, experiment_id: UUID, revision: int, operations):  # type: ignore[no-untyped-def]
    return repository.create_patch_proposal(
        experiment_id,
        OWNER_ID,
        revision,
        operations,
        (),
        AssumptionSource.MODEL,
    )


def operation(kind: ExperimentPatchOperationKind, path: str, value=...):  # type: ignore[no-untyped-def]
    values = {"operation": kind, "path": path}
    if value is not ...:
        values["value"] = value
    return ExperimentPatchOperation(**values)


def test_proposal_cursor_pagination_and_version_proposal_cross_owner_hiding(
    tmp_path: Path,
) -> None:
    """Catches ignored proposal cursors or list APIs that reveal another owner's resources."""
    repository = make_repository(tmp_path)
    experiment, _ = create_experiment(repository)
    repository.create_version(
        experiment.id, OWNER_ID, ExperimentVersionCreateRequest(expected_revision=1)
    )
    created = [
        proposal(
            repository,
            experiment.id,
            1,
            (operation(ExperimentPatchOperationKind.ADD, f"/visualization/value_{index}", index),),
        )
        for index in range(3)
    ]
    ordered = sorted(created, key=lambda item: str(item.id))

    first = repository.list_patch_proposals(
        experiment.id, OWNER_ID, cursor=None, limit=2
    )
    second = repository.list_patch_proposals(
        experiment.id, OWNER_ID, cursor=first.next_cursor, limit=2
    )

    assert list(first.items) == ordered[:2]
    assert first.next_cursor == ordered[1].id
    assert list(second.items) == ordered[2:]
    assert second.next_cursor is None
    assert_error(
        lambda: repository.list_versions(experiment.id, OTHER_OWNER_ID, cursor=None, limit=10),
        "experiment_not_found",
    )
    assert_error(
        lambda: repository.list_patch_proposals(
            experiment.id, OTHER_OWNER_ID, cursor=None, limit=10
        ),
        "experiment_not_found",
    )


def test_complex_frozen_json_roundtrips_through_canonical_db_and_pydantic(
    tmp_path: Path,
) -> None:
    """Catches lossy model_dump persistence or reconstruction without Task 1 validation."""
    engine = migrated_engine(tmp_path)
    repository = repository_type()(engine)
    experiment, _ = create_experiment(repository)
    assumption = ExperimentAssumption(
        id=uuid4(),
        statement="Boundary flux stays finite.",
        source=AssumptionSource.USER,
        status=AssumptionStatus.ACCEPTED,
        created_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )
    request = ExperimentDraftUpdateRequest(
        expected_revision=1,
        model_spec=ModelSpec(
            schema_version="1.0",
            domain_kind=ExperimentDomainKind.PDE,
            plugin_id="solver.nested",
            plugin_version="2.0",
            payload={
                "mesh": {"levels": [1, 2, {"enabled": True, "weight": 0.25}]},
                "nullable": None,
            },
        ),
        parameters=(
            ExperimentParameter(
                key="solver.step",
                label="Step",
                value={"schedule": [0.1, {"adaptive": False}]},
                unit="s",
            ),
        ),
        observables=(
            ExperimentObservable(
                key="field.energy",
                label="Energy",
                description="Nested roundtrip observable",
                unit="J",
            ),
        ),
        assumptions=(assumption,),
        visualization={
            "layers": [{"name": "surface", "visible": True, "points": [[0, 1], [2, 3]]}]
        },
        code_files=(
            ExperimentCodeFile(path="nested/model.py", language="python", content="MODEL = True\n"),
        ),
    )
    updated = repository.update_draft(experiment.id, OWNER_ID, request)
    loaded = repository.get_draft(experiment.id, OWNER_ID)
    version, created = repository.create_version(
        experiment.id,
        OWNER_ID,
        ExperimentVersionCreateRequest(expected_revision=updated.revision),
    )
    listed = repository.list_versions(experiment.id, OWNER_ID, cursor=None, limit=10).items[0]
    expected = updated.model_dump(mode="json")

    assert created is True
    assert loaded.model_dump(mode="json") == expected
    for field in (
        "model_spec",
        "parameters",
        "observables",
        "assumptions",
        "visualization",
        "code_files",
    ):
        assert listed.model_dump(mode="json")[field] == expected[field]
        assert version.model_dump(mode="json")[field] == expected[field]
    assert isinstance(loaded.visualization, MappingProxyType)
    assert isinstance(loaded.visualization["layers"], tuple)
    assert isinstance(loaded.visualization["layers"][0], MappingProxyType)
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT model_spec_json, parameters_json, observables_json, assumptions_json, "
                "visualization_json, code_files_json FROM experiment_drafts "
                "WHERE experiment_id = :experiment_id"
            ),
            {"experiment_id": str(experiment.id)},
        ).one()
    for index, field in enumerate(
        (
            "model_spec",
            "parameters",
            "observables",
            "assumptions",
            "visualization",
            "code_files",
        )
    ):
        assert json.loads(row[index]) == expected[field]


def test_apply_rolls_back_draft_cas_when_proposal_transition_trigger_fails(
    tmp_path: Path,
) -> None:
    """Catches a transaction boundary that commits the draft before proposal resolution."""
    engine = migrated_engine(tmp_path)
    repository = repository_type()(engine)
    experiment, original = create_experiment(repository)
    pending = proposal(
        repository,
        experiment.id,
        original.revision,
        (operation(ExperimentPatchOperationKind.ADD, "/visualization/should_rollback", True),),
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER test_fail_proposal_transition "
                "BEFORE UPDATE ON experiment_patch_proposals "
                "BEGIN "
                "SELECT RAISE(ABORT, 'forced proposal transition failure'); END"
            )
        )

    with pytest.raises(IntegrityError, match="forced proposal transition failure"):
        repository.apply_patch_proposal(
            experiment.id,
            pending.id,
            OWNER_ID,
            ExperimentPatchProposalApplyRequest(expected_revision=original.revision),
        )

    assert repository.get_draft(experiment.id, OWNER_ID) == original
    stored = repository.list_patch_proposals(
        experiment.id, OWNER_ID, cursor=None, limit=10
    ).items[0]
    assert stored.status.value == "pending"
    assert stored.resolved_at is None


def test_patch_proposals_apply_rfc6902_subset_and_preserve_rollback_on_invalid_patch(
    tmp_path: Path,
) -> None:
    """Catches bad pointer escapes, array semantics, or partially persisted invalid patches."""
    repository = make_repository(tmp_path)
    experiment, _ = create_experiment(repository)
    draft = repository.update_draft(
        experiment.id,
        OWNER_ID,
        ExperimentDraftUpdateRequest(
            expected_revision=1,
            visualization={"items": ["a", "remove-me", "c"], "remove_me": True},
        ),
    )
    valid = proposal(
        repository,
        experiment.id,
        draft.revision,
        (
            operation(ExperimentPatchOperationKind.ADD, "/visualization/items/1", "inserted"),
            operation(ExperimentPatchOperationKind.REMOVE, "/visualization/items/2"),
            operation(ExperimentPatchOperationKind.ADD, "/visualization/items/-", "b"),
            operation(ExperimentPatchOperationKind.REPLACE, "/visualization/items/0", "A"),
            operation(ExperimentPatchOperationKind.REMOVE, "/visualization/remove_me"),
            operation(ExperimentPatchOperationKind.ADD, "/visualization/a~1b", True),
            operation(ExperimentPatchOperationKind.ADD, "/visualization/t~0key", 1),
        ),
    )
    applied = repository.apply_patch_proposal(
        experiment.id,
        valid.id,
        OWNER_ID,
        ExperimentPatchProposalApplyRequest(expected_revision=draft.revision),
    )

    assert applied.revision == 3
    assert applied.model_dump(mode="json")["visualization"] == {
        "items": ["A", "inserted", "c", "b"],
        "a/b": True,
        "t~key": 1,
    }
    proposals = repository.list_patch_proposals(experiment.id, OWNER_ID, cursor=None, limit=10)
    assert proposals.items[0].status.value == "applied"
    for operations in (
        (operation(ExperimentPatchOperationKind.REPLACE, "/revision", 4),),
        (operation(ExperimentPatchOperationKind.ADD, "/visualization/missing/child", True),),
        (operation(ExperimentPatchOperationKind.REPLACE, "/visualization/missing", True),),
        (operation(ExperimentPatchOperationKind.REMOVE, "/visualization/missing"),),
        (operation(ExperimentPatchOperationKind.ADD, "/visualization/items/-1", True),),
        (operation(ExperimentPatchOperationKind.ADD, "/visualization/items/1.0", True),),
        (operation(ExperimentPatchOperationKind.ADD, "/visualization/items/99", True),),
        (operation(ExperimentPatchOperationKind.ADD, "/visualization/~2", True),),
        (operation(ExperimentPatchOperationKind.REPLACE, "/model_spec/plugin_id", "x"),),
        (operation(ExperimentPatchOperationKind.REPLACE, "/visualization/items/-", True),),
        (operation(ExperimentPatchOperationKind.REMOVE, "/visualization/items/-"),),
    ):
        invalid = proposal(repository, experiment.id, applied.revision, operations)
        assert_error(
            lambda invalid=invalid: repository.apply_patch_proposal(
                experiment.id,
                invalid.id,
                OWNER_ID,
                ExperimentPatchProposalApplyRequest(expected_revision=applied.revision),
            ),
            "experiment_patch_invalid",
        )
        assert repository.get_draft(experiment.id, OWNER_ID) == applied
        stored = next(
            item
            for item in repository.list_patch_proposals(
                experiment.id, OWNER_ID, cursor=None, limit=20
            ).items
            if item.id == invalid.id
        )
        assert stored.status.value == "pending"


def test_proposals_reject_stale_resolved_cross_owner_and_concurrent_outcomes(
    tmp_path: Path,
) -> None:
    """Catches proposal transitions that are not CAS-protected or reveal another owner's state."""
    engine = migrated_engine(tmp_path)
    repository = repository_type()(engine)
    experiment, draft = create_experiment(repository)
    rejected = proposal(
        repository,
        experiment.id,
        draft.revision,
        (operation(ExperimentPatchOperationKind.ADD, "/visualization/rejected", True),),
    )
    outcome = repository.reject_patch_proposal(
        experiment.id,
        rejected.id,
        OWNER_ID,
        ExperimentPatchProposalRejectRequest(expected_revision=1, reason="Not appropriate."),
    )
    assert outcome.status.value == "rejected" and outcome.resolved_at is not None
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT rejection_reason FROM experiment_patch_proposals WHERE id = :id"),
                {"id": str(rejected.id)},
            ).scalar_one()
            == "Not appropriate."
        )
    assert_error(
        lambda: repository.reject_patch_proposal(
            experiment.id,
            rejected.id,
            OWNER_ID,
            ExperimentPatchProposalRejectRequest(expected_revision=1),
        ),
        "experiment_proposal_resolved",
    )
    assert_error(
        lambda: repository.apply_patch_proposal(
            experiment.id,
            rejected.id,
            OTHER_OWNER_ID,
            ExperimentPatchProposalApplyRequest(expected_revision=1),
        ),
        "experiment_not_found",
    )

    stale = proposal(
        repository,
        experiment.id,
        1,
        (operation(ExperimentPatchOperationKind.ADD, "/visualization/stale", True),),
    )
    current = repository.update_draft(
        experiment.id,
        OWNER_ID,
        ExperimentDraftUpdateRequest(expected_revision=1, visualization={"changed": True}),
    )
    assert_error(
        lambda: repository.apply_patch_proposal(
            experiment.id,
            stale.id,
            OWNER_ID,
            ExperimentPatchProposalApplyRequest(expected_revision=current.revision),
        ),
        "experiment_revision_conflict",
    )

    concurrent = proposal(
        repository,
        experiment.id,
        current.revision,
        (operation(ExperimentPatchOperationKind.ADD, "/visualization/winner", True),),
    )
    barrier = Barrier(2)

    def apply() -> str:
        barrier.wait()
        try:
            repository.apply_patch_proposal(
                experiment.id,
                concurrent.id,
                OWNER_ID,
                ExperimentPatchProposalApplyRequest(expected_revision=current.revision),
            )
            return "applied"
        except ExperimentRepositoryError as error:
            return error.code

    def reject() -> str:
        barrier.wait()
        try:
            repository.reject_patch_proposal(
                experiment.id,
                concurrent.id,
                OWNER_ID,
                ExperimentPatchProposalRejectRequest(expected_revision=current.revision),
            )
            return "rejected"
        except ExperimentRepositoryError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda fn: fn(), (apply, reject)))

    assert "experiment_proposal_resolved" in outcomes
    assert set(outcomes) <= {"applied", "rejected", "experiment_proposal_resolved"}
    final = next(
        item
        for item in repository.list_patch_proposals(
            experiment.id, OWNER_ID, cursor=None, limit=20
        ).items
        if item.id == concurrent.id
    )
    assert final.status.value in {"applied", "rejected"}
