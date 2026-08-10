from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from manim_workbench_contracts import (
    AssumptionSource,
    Experiment,
    ExperimentCreateRequest,
    ExperimentDraft,
    ExperimentDraftUpdateRequest,
    ExperimentPage,
    ExperimentPatchOperation,
    ExperimentPatchProposal,
    ExperimentPatchProposalApplyRequest,
    ExperimentPatchProposalPage,
    ExperimentPatchProposalRejectRequest,
    ExperimentPatchProposalStatus,
    ExperimentVersion,
    ExperimentVersionCreateRequest,
    ExperimentVersionPage,
    ModelSpec,
)
from pydantic import ValidationError
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError, OperationalError

from .errors import (
    EXPERIMENT_NOT_FOUND,
    EXPERIMENT_PATCH_INVALID,
    EXPERIMENT_PROPOSAL_NOT_FOUND,
    EXPERIMENT_PROPOSAL_RESOLVED,
    EXPERIMENT_REVISION_CONFLICT,
    PROJECT_NOT_FOUND,
)
from .patches import apply_patch
from .serialization import (
    SNAPSHOT_FIELDS,
    editable_snapshot,
    json_loads,
    snapshot_columns,
    snapshot_hash,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExperimentRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_experiment(
        self,
        project_id: UUID,
        owner_id: UUID,
        request: ExperimentCreateRequest,
    ) -> tuple[Experiment, ExperimentDraft]:
        created_at = utc_now()
        experiment = Experiment(
            id=uuid4(),
            project_id=project_id,
            owner_id=owner_id,
            title=request.title,
            created_at=created_at,
            archived_at=None,
        )
        draft = ExperimentDraft(
            experiment_id=experiment.id,
            project_id=project_id,
            owner_id=owner_id,
            revision=1,
            model_spec=ModelSpec(
                schema_version="1.0",
                domain_kind=request.domain_kind,
                plugin_id="core.generic",
                plugin_version="1.0",
                payload={},
            ),
            parameters=(),
            observables=(),
            assumptions=(),
            visualization={},
            code_files=(),
            updated_at=created_at,
        )
        with self._engine.begin() as connection:
            self._require_project(connection, project_id, owner_id)
            connection.execute(
                text(
                    "INSERT INTO experiments "
                    "(id, project_id, owner_id, title, domain_kind, created_at, archived_at) "
                    "VALUES "
                    "(:id, :project_id, :owner_id, :title, :domain_kind, :created_at, NULL)"
                ),
                {
                    "id": str(experiment.id),
                    "project_id": str(project_id),
                    "owner_id": str(owner_id),
                    "title": experiment.title,
                    "domain_kind": request.domain_kind.value,
                    "created_at": created_at.isoformat(),
                },
            )
            self._insert_draft(connection, draft)
        return experiment, draft

    def list_experiments(
        self,
        project_id: UUID,
        owner_id: UUID,
        cursor: UUID | None,
        limit: int,
    ) -> ExperimentPage:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT id, project_id, owner_id, title, created_at, archived_at "
                        "FROM experiments "
                        "WHERE project_id = :project_id AND owner_id = :owner_id "
                        "AND (:cursor IS NULL OR id > :cursor) ORDER BY id ASC LIMIT :fetch_limit"
                    ),
                    {
                        "project_id": str(project_id),
                        "owner_id": str(owner_id),
                        "cursor": str(cursor) if cursor else None,
                        "fetch_limit": limit + 1,
                    },
                )
                .mappings()
                .all()
            )
        visible = rows[:limit]
        return ExperimentPage(
            items=tuple(self._experiment_from_row(row) for row in visible),
            next_cursor=UUID(str(visible[-1]["id"])) if len(rows) > limit and visible else None,
        )

    def get_experiment(self, experiment_id: UUID, owner_id: UUID) -> Experiment:
        with self._engine.connect() as connection:
            return self._require_experiment(connection, experiment_id, owner_id)

    def get_draft(self, experiment_id: UUID, owner_id: UUID) -> ExperimentDraft:
        with self._engine.connect() as connection:
            self._require_experiment(connection, experiment_id, owner_id)
            row = self._draft_row(connection, experiment_id, owner_id)
        if row is None:
            raise EXPERIMENT_NOT_FOUND
        return self._draft_from_row(row)

    def update_draft(
        self,
        experiment_id: UUID,
        owner_id: UUID,
        request: ExperimentDraftUpdateRequest,
    ) -> ExperimentDraft:
        replacements = self._update_values(request)
        updated_at = utc_now()
        assignments = ["revision = revision + 1", "updated_at = :updated_at"]
        parameters: dict[str, Any] = {
            "experiment_id": str(experiment_id),
            "owner_id": str(owner_id),
            "expected_revision": request.expected_revision,
            "updated_at": updated_at.isoformat(),
        }
        for field, value in replacements.items():
            column = f"{field}_json"
            assignments.append(f"{column} = :{column}")
            parameters[column] = value
        with self._engine.begin() as connection:
            self._require_experiment(connection, experiment_id, owner_id)
            row = (
                connection.execute(
                    text(
                        "UPDATE experiment_drafts SET "
                        + ", ".join(assignments)
                        + " WHERE experiment_id = :experiment_id AND owner_id = :owner_id "
                        "AND revision = :expected_revision "
                        "RETURNING experiment_id, project_id, owner_id, revision, model_spec_json, "
                        "parameters_json, observables_json, assumptions_json, visualization_json, "
                        "code_files_json, updated_at"
                    ),
                    parameters,
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise EXPERIMENT_REVISION_CONFLICT
        return self._draft_from_row(row)

    def create_version(
        self,
        experiment_id: UUID,
        owner_id: UUID,
        request: ExperimentVersionCreateRequest,
    ) -> tuple[ExperimentVersion, bool]:
        try:
            with self._write_connection() as connection:
                self._require_experiment(connection, experiment_id, owner_id)
                draft_row = self._draft_row(connection, experiment_id, owner_id)
                if draft_row is None:
                    raise EXPERIMENT_NOT_FOUND
                draft = self._draft_from_row(draft_row)
                if draft.revision != request.expected_revision:
                    raise EXPERIMENT_REVISION_CONFLICT
                snapshot = editable_snapshot(draft)
                content_hash = snapshot_hash(snapshot)
                existing = self._version_by_hash(connection, experiment_id, content_hash)
                if existing is not None:
                    return self._version_from_row(existing), False
                previous = (
                    connection.execute(
                        text(
                            "SELECT id, version FROM experiment_versions "
                            "WHERE experiment_id = :experiment_id "
                            "ORDER BY version DESC LIMIT 1"
                        ),
                        {"experiment_id": str(experiment_id)},
                    )
                    .mappings()
                    .one_or_none()
                )
                version = 1 if previous is None else int(previous["version"]) + 1
                parent_version_id = None if previous is None else UUID(str(previous["id"]))
                record = ExperimentVersion(
                    id=uuid4(),
                    experiment_id=experiment_id,
                    project_id=draft.project_id,
                    owner_id=owner_id,
                    version=version,
                    parent_version_id=parent_version_id,
                    draft_revision=draft.revision,
                    content_hash=content_hash,
                    created_at=utc_now(),
                    **snapshot,
                )
                self._insert_version(connection, record, snapshot)
                return record, True
        except (IntegrityError, OperationalError) as error:
            existing = self._read_version_by_hash(
                experiment_id,
                owner_id,
                self._snapshot_hash_at_revision(experiment_id, owner_id, request.expected_revision),
            )
            if existing is not None:
                return existing, False
            if isinstance(error, IntegrityError) or "locked" in str(error).lower():
                raise EXPERIMENT_REVISION_CONFLICT from error
            raise

    def list_versions(
        self,
        experiment_id: UUID,
        owner_id: UUID,
        cursor: int | None,
        limit: int,
    ) -> ExperimentVersionPage:
        with self._engine.connect() as connection:
            self._require_experiment(connection, experiment_id, owner_id)
            rows = (
                connection.execute(
                    text(
                        "SELECT id, experiment_id, project_id, owner_id, version, "
                        "parent_version_id, "
                        "draft_revision, model_spec_json, parameters_json, observables_json, "
                        "assumptions_json, visualization_json, code_files_json, content_hash, "
                        "created_at FROM experiment_versions "
                        "WHERE experiment_id = :experiment_id AND owner_id = :owner_id "
                        "AND (:cursor IS NULL OR version < :cursor) ORDER BY version DESC "
                        "LIMIT :fetch_limit"
                    ),
                    {
                        "experiment_id": str(experiment_id),
                        "owner_id": str(owner_id),
                        "cursor": cursor,
                        "fetch_limit": limit + 1,
                    },
                )
                .mappings()
                .all()
            )
        visible = rows[:limit]
        return ExperimentVersionPage(
            items=tuple(self._version_from_row(row) for row in visible),
            next_cursor=int(visible[-1]["version"]) if len(rows) > limit and visible else None,
        )

    def create_patch_proposal(
        self,
        experiment_id: UUID,
        owner_id: UUID,
        expected_revision: int,
        operations: Sequence[ExperimentPatchOperation],
        assumptions: Sequence[Any],
        source: AssumptionSource,
    ) -> ExperimentPatchProposal:
        created_at = utc_now()
        with self._engine.begin() as connection:
            experiment = self._require_experiment(connection, experiment_id, owner_id)
            proposal = ExperimentPatchProposal(
                id=uuid4(),
                experiment_id=experiment_id,
                project_id=experiment.project_id,
                owner_id=owner_id,
                expected_revision=expected_revision,
                status=ExperimentPatchProposalStatus.PENDING,
                operations=tuple(operations),
                assumptions=tuple(assumptions),
                source=source,
                created_at=created_at,
                resolved_at=None,
            )
            dumped = proposal.model_dump(mode="json")
            connection.execute(
                text(
                    "INSERT INTO experiment_patch_proposals "
                    "(id, experiment_id, project_id, owner_id, expected_revision, status, "
                    "operations_json, "
                    "assumptions_json, source, created_at, resolved_at, rejection_reason) VALUES "
                    "(:id, :experiment_id, :project_id, :owner_id, :expected_revision, :status, "
                    ":operations_json, :assumptions_json, :source, :created_at, NULL, NULL)"
                ),
                {
                    "id": str(proposal.id),
                    "experiment_id": str(experiment_id),
                    "project_id": str(experiment.project_id),
                    "owner_id": str(owner_id),
                    "expected_revision": expected_revision,
                    "status": proposal.status.value,
                    "operations_json": self._canonical(dumped["operations"]),
                    "assumptions_json": self._canonical(dumped["assumptions"]),
                    "source": source.value,
                    "created_at": created_at.isoformat(),
                },
            )
        return proposal

    def list_patch_proposals(
        self,
        experiment_id: UUID,
        owner_id: UUID,
        cursor: UUID | None,
        limit: int,
    ) -> ExperimentPatchProposalPage:
        with self._engine.connect() as connection:
            self._require_experiment(connection, experiment_id, owner_id)
            rows = (
                connection.execute(
                    text(
                        "SELECT id, experiment_id, project_id, owner_id, expected_revision, "
                        "status, "
                        "operations_json, assumptions_json, source, created_at, resolved_at "
                        "FROM experiment_patch_proposals WHERE experiment_id = :experiment_id "
                        "AND owner_id = :owner_id AND (:cursor IS NULL OR id > :cursor) "
                        "ORDER BY id ASC LIMIT :fetch_limit"
                    ),
                    {
                        "experiment_id": str(experiment_id),
                        "owner_id": str(owner_id),
                        "cursor": str(cursor) if cursor else None,
                        "fetch_limit": limit + 1,
                    },
                )
                .mappings()
                .all()
            )
        visible = rows[:limit]
        return ExperimentPatchProposalPage(
            items=tuple(self._proposal_from_row(row) for row in visible),
            next_cursor=UUID(str(visible[-1]["id"])) if len(rows) > limit and visible else None,
        )

    def apply_patch_proposal(
        self,
        experiment_id: UUID,
        proposal_id: UUID,
        owner_id: UUID,
        request: ExperimentPatchProposalApplyRequest,
    ) -> ExperimentDraft:
        with self._write_connection() as connection:
            experiment = self._require_experiment(connection, experiment_id, owner_id)
            proposal_row = self._proposal_row(connection, experiment_id, proposal_id, owner_id)
            if proposal_row is None:
                raise EXPERIMENT_PROPOSAL_NOT_FOUND
            proposal = self._proposal_from_row(proposal_row)
            if proposal.status is not ExperimentPatchProposalStatus.PENDING:
                raise EXPERIMENT_PROPOSAL_RESOLVED
            draft_row = self._draft_row(connection, experiment_id, owner_id)
            if draft_row is None:
                raise EXPERIMENT_NOT_FOUND
            draft = self._draft_from_row(draft_row)
            if (
                request.expected_revision != proposal.expected_revision
                or draft.revision != proposal.expected_revision
            ):
                raise EXPERIMENT_REVISION_CONFLICT
            snapshot = apply_patch(editable_snapshot(draft), proposal.operations)
            updated_at = utc_now()
            try:
                updated = ExperimentDraft(
                    experiment_id=experiment_id,
                    project_id=experiment.project_id,
                    owner_id=owner_id,
                    revision=draft.revision + 1,
                    updated_at=updated_at,
                    **snapshot,
                )
            except ValidationError:
                raise EXPERIMENT_PATCH_INVALID from None
            result = connection.execute(
                text(
                    "UPDATE experiment_drafts SET revision = :next_revision, "
                    "model_spec_json = :model_spec_json, "
                    "parameters_json = :parameters_json, observables_json = :observables_json, "
                    "assumptions_json = :assumptions_json, "
                    "visualization_json = :visualization_json, "
                    "code_files_json = :code_files_json, updated_at = :updated_at "
                    "WHERE experiment_id = :experiment_id AND owner_id = :owner_id "
                    "AND revision = :expected_revision"
                ),
                {
                    **snapshot_columns(editable_snapshot(updated)),
                    "next_revision": updated.revision,
                    "updated_at": updated_at.isoformat(),
                    "experiment_id": str(experiment_id),
                    "owner_id": str(owner_id),
                    "expected_revision": draft.revision,
                },
            )
            if result.rowcount != 1:
                self._raise_apply_cas_failure(connection, experiment_id, proposal_id, owner_id)
            transitioned = connection.execute(
                text(
                    "UPDATE experiment_patch_proposals SET status = 'applied', "
                    "resolved_at = :resolved_at, rejection_reason = NULL "
                    "WHERE id = :proposal_id AND experiment_id = :experiment_id "
                    "AND owner_id = :owner_id AND status = 'pending'"
                ),
                {
                    "resolved_at": updated_at.isoformat(),
                    "proposal_id": str(proposal_id),
                    "experiment_id": str(experiment_id),
                    "owner_id": str(owner_id),
                },
            )
            if transitioned.rowcount != 1:
                raise EXPERIMENT_PROPOSAL_RESOLVED
        return updated

    def reject_patch_proposal(
        self,
        experiment_id: UUID,
        proposal_id: UUID,
        owner_id: UUID,
        request: ExperimentPatchProposalRejectRequest,
    ) -> ExperimentPatchProposal:
        with self._write_connection() as connection:
            self._require_experiment(connection, experiment_id, owner_id)
            proposal_row = self._proposal_row(connection, experiment_id, proposal_id, owner_id)
            if proposal_row is None:
                raise EXPERIMENT_PROPOSAL_NOT_FOUND
            proposal = self._proposal_from_row(proposal_row)
            if proposal.status is not ExperimentPatchProposalStatus.PENDING:
                raise EXPERIMENT_PROPOSAL_RESOLVED
            draft_row = self._draft_row(connection, experiment_id, owner_id)
            if draft_row is None:
                raise EXPERIMENT_NOT_FOUND
            if (
                request.expected_revision != proposal.expected_revision
                or int(draft_row["revision"]) != proposal.expected_revision
            ):
                raise EXPERIMENT_REVISION_CONFLICT
            resolved_at = utc_now()
            row = (
                connection.execute(
                    text(
                        "UPDATE experiment_patch_proposals SET status = 'rejected', "
                        "resolved_at = :resolved_at, rejection_reason = :rejection_reason "
                        "WHERE id = :proposal_id AND experiment_id = :experiment_id "
                        "AND owner_id = :owner_id AND status = 'pending' "
                        "RETURNING id, experiment_id, project_id, owner_id, expected_revision, "
                        "status, "
                        "operations_json, assumptions_json, source, created_at, resolved_at"
                    ),
                    {
                        "resolved_at": resolved_at.isoformat(),
                        "rejection_reason": request.reason,
                        "proposal_id": str(proposal_id),
                        "experiment_id": str(experiment_id),
                        "owner_id": str(owner_id),
                    },
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise EXPERIMENT_PROPOSAL_RESOLVED
        return self._proposal_from_row(row)

    @contextmanager
    def _write_connection(self) -> Iterator[Connection]:
        connection = self._engine.connect()
        try:
            if self._engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.begin()
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _require_project(connection: Connection, project_id: UUID, owner_id: UUID) -> None:
        row = connection.execute(
            text("SELECT id FROM projects WHERE id = :project_id AND owner_id = :owner_id"),
            {"project_id": str(project_id), "owner_id": str(owner_id)},
        ).one_or_none()
        if row is None:
            raise PROJECT_NOT_FOUND

    def _require_experiment(
        self, connection: Connection, experiment_id: UUID, owner_id: UUID
    ) -> Experiment:
        row = (
            connection.execute(
                text(
                    "SELECT id, project_id, owner_id, title, created_at, archived_at "
                    "FROM experiments "
                    "WHERE id = :experiment_id AND owner_id = :owner_id"
                ),
                {"experiment_id": str(experiment_id), "owner_id": str(owner_id)},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise EXPERIMENT_NOT_FOUND
        return self._experiment_from_row(row)

    @staticmethod
    def _draft_row(
        connection: Connection, experiment_id: UUID, owner_id: UUID
    ) -> Mapping[str, Any] | None:
        return (
            connection.execute(
                text(
                    "SELECT experiment_id, project_id, owner_id, revision, model_spec_json, "
                    "parameters_json, observables_json, assumptions_json, visualization_json, "
                    "code_files_json, updated_at FROM experiment_drafts "
                    "WHERE experiment_id = :experiment_id AND owner_id = :owner_id"
                ),
                {"experiment_id": str(experiment_id), "owner_id": str(owner_id)},
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _proposal_row(
        connection: Connection, experiment_id: UUID, proposal_id: UUID, owner_id: UUID
    ) -> Mapping[str, Any] | None:
        return (
            connection.execute(
                text(
                    "SELECT id, experiment_id, project_id, owner_id, expected_revision, status, "
                    "operations_json, assumptions_json, source, created_at, resolved_at "
                    "FROM experiment_patch_proposals WHERE id = :proposal_id "
                    "AND experiment_id = :experiment_id AND owner_id = :owner_id"
                ),
                {
                    "proposal_id": str(proposal_id),
                    "experiment_id": str(experiment_id),
                    "owner_id": str(owner_id),
                },
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _insert_draft(connection: Connection, draft: ExperimentDraft) -> None:
        connection.execute(
            text(
                "INSERT INTO experiment_drafts "
                "(experiment_id, project_id, owner_id, revision, model_spec_json, parameters_json, "
                "observables_json, assumptions_json, visualization_json, code_files_json, "
                "updated_at) "
                "VALUES (:experiment_id, :project_id, :owner_id, :revision, :model_spec_json, "
                ":parameters_json, :observables_json, :assumptions_json, :visualization_json, "
                ":code_files_json, :updated_at)"
            ),
            {
                **snapshot_columns(editable_snapshot(draft)),
                "experiment_id": str(draft.experiment_id),
                "project_id": str(draft.project_id),
                "owner_id": str(draft.owner_id),
                "revision": draft.revision,
                "updated_at": draft.updated_at.isoformat(),
            },
        )

    @staticmethod
    def _insert_version(
        connection: Connection, record: ExperimentVersion, snapshot: Mapping[str, Any]
    ) -> None:
        connection.execute(
            text(
                "INSERT INTO experiment_versions "
                "(id, experiment_id, project_id, owner_id, version, parent_version_id, "
                "draft_revision, model_spec_json, parameters_json, observables_json, "
                "assumptions_json, visualization_json, "
                "code_files_json, content_hash, created_at) VALUES "
                "(:id, :experiment_id, :project_id, :owner_id, :version, :parent_version_id, "
                ":draft_revision, :model_spec_json, :parameters_json, :observables_json, "
                ":assumptions_json, :visualization_json, :code_files_json, :content_hash, "
                ":created_at)"
            ),
            {
                **snapshot_columns(snapshot),
                "id": str(record.id),
                "experiment_id": str(record.experiment_id),
                "project_id": str(record.project_id),
                "owner_id": str(record.owner_id),
                "version": record.version,
                "parent_version_id": str(record.parent_version_id)
                if record.parent_version_id
                else None,
                "draft_revision": record.draft_revision,
                "content_hash": record.content_hash,
                "created_at": record.created_at.isoformat(),
            },
        )

    @staticmethod
    def _version_by_hash(
        connection: Connection, experiment_id: UUID, content_hash: str
    ) -> Mapping[str, Any] | None:
        return (
            connection.execute(
                text(
                    "SELECT id, experiment_id, project_id, owner_id, version, parent_version_id, "
                    "draft_revision, model_spec_json, parameters_json, observables_json, "
                    "assumptions_json, visualization_json, code_files_json, content_hash, "
                    "created_at FROM experiment_versions "
                    "WHERE experiment_id = :experiment_id AND content_hash = :content_hash"
                ),
                {"experiment_id": str(experiment_id), "content_hash": content_hash},
            )
            .mappings()
            .one_or_none()
        )

    def _read_version_by_hash(
        self, experiment_id: UUID, owner_id: UUID, content_hash: str | None
    ) -> ExperimentVersion | None:
        if content_hash is None:
            return None
        with self._engine.connect() as connection:
            row = self._version_by_hash(connection, experiment_id, content_hash)
            if row is None or str(row["owner_id"]) != str(owner_id):
                return None
            return self._version_from_row(row)

    def _snapshot_hash_at_revision(
        self, experiment_id: UUID, owner_id: UUID, expected_revision: int
    ) -> str | None:
        with self._engine.connect() as connection:
            row = self._draft_row(connection, experiment_id, owner_id)
        if row is None or int(row["revision"]) != expected_revision:
            return None
        return snapshot_hash(editable_snapshot(self._draft_from_row(row)))

    @staticmethod
    def _update_values(request: ExperimentDraftUpdateRequest) -> dict[str, str]:
        dumped = request.model_dump(mode="json")
        return {
            field: ExperimentRepository._canonical(dumped[field])
            for field in SNAPSHOT_FIELDS
            if field in request.model_fields_set
        }

    @staticmethod
    def _canonical(value: Any) -> str:
        from .serialization import canonical_json

        return canonical_json(value)

    @staticmethod
    def _experiment_from_row(row: Mapping[str, Any]) -> Experiment:
        return Experiment.model_validate(dict(row))

    @staticmethod
    def _draft_from_row(row: Mapping[str, Any]) -> ExperimentDraft:
        values = dict(row)
        for field in SNAPSHOT_FIELDS:
            values[field] = json_loads(values.pop(f"{field}_json"))
        return ExperimentDraft.model_validate(values)

    @staticmethod
    def _version_from_row(row: Mapping[str, Any]) -> ExperimentVersion:
        values = dict(row)
        for field in SNAPSHOT_FIELDS:
            values[field] = json_loads(values.pop(f"{field}_json"))
        return ExperimentVersion.model_validate(values)

    @staticmethod
    def _proposal_from_row(row: Mapping[str, Any]) -> ExperimentPatchProposal:
        values = dict(row)
        values["operations"] = json_loads(values.pop("operations_json"))
        values["assumptions"] = json_loads(values.pop("assumptions_json"))
        return ExperimentPatchProposal.model_validate(values)

    @staticmethod
    def _raise_apply_cas_failure(
        connection: Connection, experiment_id: UUID, proposal_id: UUID, owner_id: UUID
    ) -> None:
        row = ExperimentRepository._proposal_row(connection, experiment_id, proposal_id, owner_id)
        if row is not None and row["status"] != ExperimentPatchProposalStatus.PENDING.value:
            raise EXPERIMENT_PROPOSAL_RESOLVED
        raise EXPERIMENT_REVISION_CONFLICT
