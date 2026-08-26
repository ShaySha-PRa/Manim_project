from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from manim_workbench_contracts import (
    CompositionManifest,
    CompositionRun,
    CompositionRunStatus,
    GlobalBrief,
    RenderProfile,
    SceneBlockRun,
    SceneBlockRunStatus,
    SceneBlockVersion,
    ScenePipeline,
    ScenePipelineMode,
    SceneRunProvenance,
    VideoWorkflowVersion,
    WorkflowEdge,
    WorkflowNode,
)
from pydantic import TypeAdapter
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError, OperationalError

from .cache import CacheArtifactDescriptor
from .errors import (
    WORKFLOW_NOT_FOUND,
    WORKFLOW_REFERENCE_INVALID,
    WORKFLOW_VERSION_CONFLICT,
)
from .models import SceneBlockRecord, SceneBlockVersionDetail, VideoWorkflowRecord
from .validation import validate_linear_workflow

_NODES = TypeAdapter(tuple[WorkflowNode, ...])
_EDGES = TypeAdapter(tuple[WorkflowEdge, ...])


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _datetime(value: object) -> datetime:
    return datetime.fromisoformat(str(value))


def _uuid(value: object | None) -> UUID | None:
    return UUID(str(value)) if value is not None else None


def _json_value(value: Any | None) -> str | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, tuple):
        value = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in value
        ]
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class WorkflowRepository:
    """Immutable workflow persistence with owner-scoped event projections."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_workflow(self, project_id: UUID, owner_id: UUID) -> UUID:
        workflow_id = uuid4()
        now = utc_now()
        with self._engine.begin() as connection:
            self._require_active_project(connection, project_id, owner_id)
            connection.execute(
                text(
                    "INSERT INTO video_workflows (id,project_id,owner_id,created_at) "
                    "VALUES (:id,:project_id,:owner_id,:created_at)"
                ),
                self._identity_values(workflow_id, project_id, owner_id, now),
            )
        return workflow_id

    def get_workflow(self, workflow_id: UUID, owner_id: UUID) -> VideoWorkflowRecord:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT w.* FROM video_workflows w JOIN projects p ON p.id=w.project_id "
                        "WHERE w.id=:id AND w.owner_id=:owner_id AND p.owner_id=:owner_id "
                        "AND p.archived_at IS NULL"
                    ),
                    {"id": str(workflow_id), "owner_id": str(owner_id)},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise WORKFLOW_NOT_FOUND
        return VideoWorkflowRecord(
            id=UUID(str(row["id"])),
            project_id=UUID(str(row["project_id"])),
            owner_id=UUID(str(row["owner_id"])),
            created_at=_datetime(row["created_at"]),
        )

    def list_workflow_versions(
        self, workflow_id: UUID, owner_id: UUID
    ) -> tuple[VideoWorkflowVersion, ...]:
        workflow = self.get_workflow(workflow_id, owner_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT * FROM video_workflow_versions WHERE workflow_id=:workflow_id "
                        "AND project_id=:project_id AND owner_id=:owner_id ORDER BY version"
                    ),
                    {
                        "workflow_id": str(workflow_id),
                        "project_id": str(workflow.project_id),
                        "owner_id": str(owner_id),
                    },
                )
                .mappings()
                .all()
            )
        return tuple(self._workflow_from_row(row) for row in rows)

    def create_scene_block(
        self,
        *,
        workflow_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        title: str,
        prompt: str,
        pipeline_mode: ScenePipelineMode,
        target_duration_seconds: int,
        asset_version_ids: tuple[UUID, ...] = (),
    ) -> SceneBlockVersion:
        return self.create_scene_block_record(
            workflow_id=workflow_id,
            project_id=project_id,
            owner_id=owner_id,
            title=title,
            prompt=prompt,
            pipeline_mode=pipeline_mode,
            target_duration_seconds=target_duration_seconds,
            asset_version_ids=asset_version_ids,
        )[1]

    def create_scene_block_record(
        self,
        *,
        workflow_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        title: str,
        prompt: str,
        pipeline_mode: ScenePipelineMode,
        target_duration_seconds: int,
        asset_version_ids: tuple[UUID, ...] = (),
    ) -> tuple[SceneBlockRecord, SceneBlockVersion]:
        block_id = uuid4()
        now = utc_now()
        record = SceneBlockVersion(
            id=uuid4(),
            workflow_id=workflow_id,
            project_id=project_id,
            owner_id=owner_id,
            version=1,
            parent_version_id=None,
            title=title,
            prompt=prompt,
            pipeline_mode=pipeline_mode,
            target_duration_seconds=target_duration_seconds,
            asset_version_ids=asset_version_ids,
            created_at=now,
        )
        with self._engine.begin() as connection:
            self._require_workflow(connection, workflow_id, project_id, owner_id)
            self._require_assets(connection, asset_version_ids, project_id, owner_id)
            connection.execute(
                text(
                    "INSERT INTO scene_blocks (id,workflow_id,project_id,owner_id,created_at) "
                    "VALUES (:id,:workflow_id,:project_id,:owner_id,:created_at)"
                ),
                {
                    **self._identity_values(block_id, project_id, owner_id, now),
                    "workflow_id": str(workflow_id),
                },
            )
            self._insert_scene_version(connection, block_id, record)
        return (
            SceneBlockRecord(
                id=block_id,
                workflow_id=workflow_id,
                project_id=project_id,
                owner_id=owner_id,
                created_at=now,
            ),
            record,
        )

    def get_scene_block(self, block_id: UUID, owner_id: UUID) -> SceneBlockRecord:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT b.* FROM scene_blocks b JOIN projects p ON p.id=b.project_id "
                        "WHERE b.id=:id AND b.owner_id=:owner_id AND p.owner_id=:owner_id "
                        "AND p.archived_at IS NULL"
                    ),
                    {"id": str(block_id), "owner_id": str(owner_id)},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise WORKFLOW_NOT_FOUND
        return SceneBlockRecord(
            id=UUID(str(row["id"])),
            workflow_id=UUID(str(row["workflow_id"])),
            project_id=UUID(str(row["project_id"])),
            owner_id=UUID(str(row["owner_id"])),
            created_at=_datetime(row["created_at"]),
        )

    def list_scene_block_versions(
        self, block_id: UUID, owner_id: UUID
    ) -> tuple[SceneBlockVersion, ...]:
        block = self.get_scene_block(block_id, owner_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT * FROM scene_block_versions WHERE scene_block_id=:block_id "
                        "AND project_id=:project_id AND owner_id=:owner_id ORDER BY version"
                    ),
                    {
                        "block_id": str(block_id),
                        "project_id": str(block.project_id),
                        "owner_id": str(owner_id),
                    },
                )
                .mappings()
                .all()
            )
        return tuple(self._scene_from_row(row) for row in rows)

    def append_scene_block_version(
        self,
        *,
        parent_version_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        title: str,
        prompt: str,
        pipeline_mode: ScenePipelineMode,
        target_duration_seconds: int,
        asset_version_ids: tuple[UUID, ...] = (),
        scene_block_id: UUID | None = None,
    ) -> SceneBlockVersion:
        try:
            with self._engine.begin() as connection:
                parent = self._current_scene_parent(
                    connection, parent_version_id, project_id, owner_id
                )
                if scene_block_id is not None and str(parent["scene_block_id"]) != str(
                    scene_block_id
                ):
                    raise WORKFLOW_VERSION_CONFLICT
                self._require_assets(connection, asset_version_ids, project_id, owner_id)
                record = SceneBlockVersion(
                    id=uuid4(),
                    workflow_id=UUID(str(parent["workflow_id"])),
                    project_id=project_id,
                    owner_id=owner_id,
                    version=int(parent["version"]) + 1,
                    parent_version_id=parent_version_id,
                    title=title,
                    prompt=prompt,
                    pipeline_mode=pipeline_mode,
                    target_duration_seconds=target_duration_seconds,
                    asset_version_ids=asset_version_ids,
                    created_at=utc_now(),
                )
                self._insert_scene_version(
                    connection, UUID(str(parent["scene_block_id"])), record
                )
        except (IntegrityError, OperationalError) as error:
            self._raise_conflict(error)
        return record

    def get_scene_block_version(
        self, version_id: UUID, project_id: UUID, owner_id: UUID
    ) -> SceneBlockVersion:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT v.* FROM scene_block_versions v "
                        "JOIN projects p ON p.id=v.project_id "
                        "WHERE v.id=:id AND v.project_id=:project_id AND v.owner_id=:owner_id "
                        "AND p.owner_id=:owner_id AND p.archived_at IS NULL"
                    ),
                    self._scope_values(version_id, project_id, owner_id),
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise WORKFLOW_NOT_FOUND
        return self._scene_from_row(row)

    def get_scene_block_version_detail(
        self, version_id: UUID, owner_id: UUID
    ) -> SceneBlockVersionDetail:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT v.* FROM scene_block_versions v JOIN projects p "
                        "ON p.id=v.project_id WHERE v.id=:id AND v.owner_id=:owner_id "
                        "AND p.owner_id=:owner_id AND p.archived_at IS NULL"
                    ),
                    {"id": str(version_id), "owner_id": str(owner_id)},
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise WORKFLOW_NOT_FOUND
        return SceneBlockVersionDetail(
            block_id=UUID(str(row["scene_block_id"])), version=self._scene_from_row(row)
        )

    def append_workflow_version(
        self,
        *,
        workflow_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        global_brief: GlobalBrief,
        nodes: tuple[WorkflowNode, ...],
        edges: tuple[WorkflowEdge, ...],
        parent_version_id: UUID | None = None,
    ) -> VideoWorkflowVersion:
        try:
            with self._engine.begin() as connection:
                self._require_workflow(connection, workflow_id, project_id, owner_id)
                current = (
                    connection.execute(
                        text(
                            "SELECT id,version FROM video_workflow_versions "
                            "WHERE workflow_id=:workflow_id AND project_id=:project_id "
                            "AND owner_id=:owner_id ORDER BY version DESC LIMIT 1"
                        ),
                        {
                            "workflow_id": str(workflow_id),
                            "project_id": str(project_id),
                            "owner_id": str(owner_id),
                        },
                    )
                    .mappings()
                    .one_or_none()
                )
                if current is None:
                    if parent_version_id is not None:
                        raise WORKFLOW_VERSION_CONFLICT
                    version = 1
                else:
                    if str(current["id"]) != str(parent_version_id):
                        raise WORKFLOW_VERSION_CONFLICT
                    version = int(current["version"]) + 1
                scene_versions = self._require_scene_references(
                    connection, nodes, workflow_id, project_id, owner_id
                )
                validate_linear_workflow(
                    global_brief=global_brief,
                    nodes=nodes,
                    edges=edges,
                    scene_versions=scene_versions,
                )
                record = VideoWorkflowVersion(
                    id=uuid4(),
                    workflow_id=workflow_id,
                    project_id=project_id,
                    owner_id=owner_id,
                    version=version,
                    parent_version_id=parent_version_id,
                    global_brief=global_brief,
                    nodes=nodes,
                    edges=edges,
                    created_at=utc_now(),
                )
                connection.execute(
                    text(
                        "INSERT INTO video_workflow_versions "
                        "(id,workflow_id,project_id,owner_id,version,parent_version_id,"
                        "global_brief_json,nodes_json,edges_json,created_at) VALUES "
                        "(:id,:workflow_id,:project_id,:owner_id,:version,:parent_version_id,"
                        ":global_brief_json,:nodes_json,:edges_json,:created_at)"
                    ),
                    {
                        "id": str(record.id),
                        "workflow_id": str(workflow_id),
                        "project_id": str(project_id),
                        "owner_id": str(owner_id),
                        "version": version,
                        "parent_version_id": (
                            str(parent_version_id) if parent_version_id else None
                        ),
                        "global_brief_json": global_brief.model_dump_json(),
                        "nodes_json": json.dumps(
                            [item.model_dump(mode="json") for item in nodes]
                        ),
                        "edges_json": json.dumps(
                            [item.model_dump(mode="json") for item in edges]
                        ),
                        "created_at": record.created_at.isoformat(),
                    },
                )
        except (IntegrityError, OperationalError) as error:
            self._raise_conflict(error)
        return record

    def get_workflow_version(
        self, version_id: UUID, project_id: UUID, owner_id: UUID
    ) -> VideoWorkflowVersion:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT v.* FROM video_workflow_versions v "
                        "JOIN projects p ON p.id=v.project_id "
                        "WHERE v.id=:id AND v.project_id=:project_id AND v.owner_id=:owner_id "
                        "AND p.owner_id=:owner_id AND p.archived_at IS NULL"
                    ),
                    self._scope_values(version_id, project_id, owner_id),
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise WORKFLOW_NOT_FOUND
        return self._workflow_from_row(row)

    def create_scene_block_run(
        self,
        *,
        scene_block_version_id: UUID,
        workflow_version_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        cache_key: str,
        idempotency_key: str,
        profile: RenderProfile = RenderProfile.PREVIEW,
    ) -> SceneBlockRun:
        run_id = uuid4()
        now = utc_now()
        try:
            with self._engine.begin() as connection:
                self._require_run_references(
                    connection,
                    scene_block_version_id,
                    workflow_version_id,
                    project_id,
                    owner_id,
                )
                connection.execute(
                    text(
                        "INSERT INTO scene_block_runs "
                        "(id,scene_block_version_id,workflow_version_id,project_id,owner_id,"
                        "profile,cache_key,idempotency_key,created_at) VALUES "
                        "(:id,:scene_version,:workflow_version,:project_id,:owner_id,"
                        ":profile,:cache_key,:idempotency_key,:created_at)"
                    ),
                    {
                        "id": str(run_id),
                        "scene_version": str(scene_block_version_id),
                        "workflow_version": str(workflow_version_id),
                        "project_id": str(project_id),
                        "owner_id": str(owner_id),
                        "profile": profile.value,
                        "cache_key": cache_key,
                        "idempotency_key": idempotency_key,
                        "created_at": now.isoformat(),
                    },
                )
                self._insert_scene_event(
                    connection,
                    run_id=run_id,
                    owner_id=owner_id,
                    state_version=0,
                    status=SceneBlockRunStatus.QUEUED,
                )
        except (IntegrityError, OperationalError) as error:
            self._raise_conflict(error)
        return self.get_scene_block_run(run_id, project_id, owner_id)

    def append_scene_block_run_event(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        expected_state_version: int,
        status: SceneBlockRunStatus,
        pipeline_used: ScenePipeline | None = None,
        intent_ref: UUID | None = None,
        animation_ir_ref: UUID | None = None,
        compiled_program_ref: UUID | None = None,
        preview_artifact_id: UUID | None = None,
        final_artifact_id: UUID | None = None,
        error_code: str | None = None,
    ) -> SceneBlockRun:
        try:
            with self._engine.begin() as connection:
                current = self._require_scene_run(
                    connection, run_id, project_id, owner_id
                )
                if int(current["state_version"]) != expected_state_version:
                    raise WORKFLOW_VERSION_CONFLICT
                self._insert_scene_event(
                    connection,
                    run_id=run_id,
                    owner_id=owner_id,
                    state_version=expected_state_version + 1,
                    status=status,
                    pipeline_used=pipeline_used,
                    intent_ref=intent_ref,
                    animation_ir_ref=animation_ir_ref,
                    compiled_program_ref=compiled_program_ref,
                    preview_artifact_id=preview_artifact_id,
                    final_artifact_id=final_artifact_id,
                    error_code=error_code,
                )
        except (IntegrityError, OperationalError) as error:
            self._raise_conflict(error)
        return self.get_scene_block_run(run_id, project_id, owner_id)

    def get_scene_block_run(
        self, run_id: UUID, project_id: UUID, owner_id: UUID
    ) -> SceneBlockRun:
        with self._engine.connect() as connection:
            row = self._require_scene_run(connection, run_id, project_id, owner_id)
        return self._scene_run_from_row(row)

    def find_scene_run_by_idempotency(
        self, idempotency_key: str, project_id: UUID, owner_id: UUID
    ) -> SceneBlockRun | None:
        with self._engine.connect() as connection:
            run_id = connection.execute(
                text(
                    "SELECT id FROM scene_block_runs WHERE idempotency_key=:key "
                    "AND project_id=:project_id AND owner_id=:owner_id"
                ),
                {
                    "key": idempotency_key,
                    "project_id": str(project_id),
                    "owner_id": str(owner_id),
                },
            ).scalar_one_or_none()
        return (
            self.get_scene_block_run(UUID(str(run_id)), project_id, owner_id)
            if run_id is not None
            else None
        )

    def persist_scene_provenance(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        intent: Any | None,
        animation_ir: Any | None,
        tool_runs: tuple[Any, ...],
        provenance: tuple[tuple[str, str], ...],
    ) -> tuple[UUID | None, UUID | None]:
        with self._engine.begin() as connection:
            self._require_scene_run(connection, run_id, project_id, owner_id)
            existing = connection.execute(
                text(
                    "SELECT intent_ref,animation_ir_ref FROM scene_run_provenance "
                    "WHERE scene_block_run_id=:run AND project_id=:project "
                    "AND owner_id=:owner"
                ),
                {
                    "run": str(run_id),
                    "project": str(project_id),
                    "owner": str(owner_id),
                },
            ).one_or_none()
            if existing is not None:
                return _uuid(existing.intent_ref), _uuid(existing.animation_ir_ref)
            intent_ref = uuid4() if intent is not None else None
            animation_ir_ref = uuid4() if animation_ir is not None else None
            connection.execute(
                text(
                    "INSERT INTO scene_run_provenance "
                    "(id,scene_block_run_id,project_id,owner_id,intent_ref,animation_ir_ref,"
                    "intent_json,animation_ir_json,tool_runs_json,provenance_json,created_at) "
                    "VALUES (:id,:run,:project,:owner,:intent_ref,:animation_ir_ref,"
                    ":intent_json,:animation_ir_json,:tool_runs_json,:provenance_json,:created)"
                ),
                {
                    "id": str(uuid4()),
                    "run": str(run_id),
                    "project": str(project_id),
                    "owner": str(owner_id),
                    "intent_ref": str(intent_ref) if intent_ref else None,
                    "animation_ir_ref": str(animation_ir_ref) if animation_ir_ref else None,
                    "intent_json": _json_value(intent),
                    "animation_ir_json": _json_value(animation_ir),
                    "tool_runs_json": _json_value(tool_runs),
                    "provenance_json": _json_value(dict(provenance)),
                    "created": utc_now().isoformat(),
                },
            )
        return intent_ref, animation_ir_ref

    def get_scene_provenance(
        self, run_id: UUID, project_id: UUID, owner_id: UUID
    ) -> SceneRunProvenance:
        with self._engine.connect() as connection:
            self._require_scene_run(connection, run_id, project_id, owner_id)
            row = connection.execute(
                text(
                    "SELECT * FROM scene_run_provenance WHERE scene_block_run_id=:run "
                    "AND project_id=:project AND owner_id=:owner"
                ),
                {"run": str(run_id), "project": str(project_id), "owner": str(owner_id)},
            ).mappings().one_or_none()
        if row is None:
            raise WORKFLOW_NOT_FOUND
        return SceneRunProvenance(
            scene_block_run_id=UUID(str(row["scene_block_run_id"])),
            project_id=UUID(str(row["project_id"])),
            owner_id=UUID(str(row["owner_id"])),
            intent_ref=_uuid(row["intent_ref"]),
            animation_ir_ref=_uuid(row["animation_ir_ref"]),
            intent=json.loads(row["intent_json"]) if row["intent_json"] else None,
            animation_ir=(
                json.loads(row["animation_ir_json"]) if row["animation_ir_json"] else None
            ),
            tool_runs=tuple(json.loads(row["tool_runs_json"])),
            provenance=dict(json.loads(row["provenance_json"])),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def clone_scene_provenance(
        self,
        *,
        source_run_id: UUID,
        target_run_id: UUID,
        project_id: UUID,
        owner_id: UUID,
    ) -> tuple[UUID | None, UUID | None]:
        """Copy immutable evidence to a cache-hit run with new run-local references."""
        with self._engine.begin() as connection:
            self._require_scene_run(connection, source_run_id, project_id, owner_id)
            self._require_scene_run(connection, target_run_id, project_id, owner_id)
            existing = connection.execute(
                text(
                    "SELECT intent_ref,animation_ir_ref FROM scene_run_provenance "
                    "WHERE scene_block_run_id=:run AND project_id=:project AND owner_id=:owner"
                ),
                {"run": str(target_run_id), "project": str(project_id),
                 "owner": str(owner_id)},
            ).one_or_none()
            if existing is not None:
                return _uuid(existing.intent_ref), _uuid(existing.animation_ir_ref)
            source = connection.execute(
                text(
                    "SELECT * FROM scene_run_provenance WHERE scene_block_run_id=:run "
                    "AND project_id=:project AND owner_id=:owner"
                ),
                {"run": str(source_run_id), "project": str(project_id),
                 "owner": str(owner_id)},
            ).mappings().one_or_none()
            if source is None:
                raise WORKFLOW_NOT_FOUND
            intent_ref = uuid4() if source["intent_ref"] is not None else None
            animation_ir_ref = uuid4() if source["animation_ir_ref"] is not None else None
            connection.execute(
                text(
                    "INSERT INTO scene_run_provenance "
                    "(id,scene_block_run_id,project_id,owner_id,intent_ref,animation_ir_ref,"
                    "intent_json,animation_ir_json,tool_runs_json,provenance_json,created_at) "
                    "VALUES (:id,:run,:project,:owner,:intent_ref,:animation_ir_ref,"
                    ":intent,:ir,:tools,:provenance,:created)"
                ),
                {
                    "id": str(uuid4()), "run": str(target_run_id),
                    "project": str(project_id), "owner": str(owner_id),
                    "intent_ref": str(intent_ref) if intent_ref else None,
                    "animation_ir_ref": str(animation_ir_ref) if animation_ir_ref else None,
                    "intent": source["intent_json"], "ir": source["animation_ir_json"],
                    "tools": source["tool_runs_json"],
                    "provenance": source["provenance_json"],
                    "created": utc_now().isoformat(),
                },
            )
        return intent_ref, animation_ir_ref

    def find_scene_cache_source_run(
        self,
        cache_key: str,
        project_id: UUID,
        owner_id: UUID,
        profile: RenderProfile,
    ) -> SceneBlockRun | None:
        artifact_column = (
            "preview_artifact_id"
            if profile is RenderProfile.PREVIEW
            else "final_artifact_id"
        )
        with self._engine.connect() as connection:
            run_id = connection.execute(
                text(
                    f"SELECT r.id FROM scene_block_runs r JOIN scene_block_run_events e "
                    f"ON e.run_id=r.id JOIN workflow_artifacts a "
                    f"ON a.id=e.{artifact_column} WHERE r.cache_key=:cache_key "
                    f"AND r.project_id=:project AND r.owner_id=:owner "
                    f"AND e.status='succeeded' AND a.profile=:profile "
                    f"AND e.state_version=(SELECT MAX(latest.state_version) FROM "
                    f"scene_block_run_events latest WHERE latest.run_id=r.id) "
                    f"ORDER BY r.created_at DESC LIMIT 1"
                ),
                {
                    "cache_key": cache_key,
                    "project": str(project_id),
                    "owner": str(owner_id),
                    "profile": profile.value,
                },
            ).scalar_one_or_none()
        return (
            self.get_scene_block_run(UUID(str(run_id)), project_id, owner_id)
            if run_id is not None
            else None
        )

    def find_composition_cache_source_run(
        self,
        cache_key: str,
        project_id: UUID,
        owner_id: UUID,
        profile: RenderProfile,
    ) -> CompositionRun | None:
        with self._engine.connect() as connection:
            run_id = connection.execute(
                text(
                    "SELECT r.id FROM workflow_composition_runs r "
                    "JOIN workflow_composition_run_events e ON e.run_id=r.id "
                    "JOIN workflow_artifacts a ON a.id=e.artifact_id "
                    "WHERE r.cache_key=:cache_key AND r.project_id=:project "
                    "AND r.owner_id=:owner AND r.profile=:profile "
                    "AND e.status='succeeded' AND e.state_version=(SELECT MAX(latest."
                    "state_version) FROM workflow_composition_run_events latest "
                    "WHERE latest.run_id=r.id) ORDER BY r.created_at DESC LIMIT 1"
                ),
                {
                    "cache_key": cache_key,
                    "project": str(project_id),
                    "owner": str(owner_id),
                    "profile": profile.value,
                },
            ).scalar_one_or_none()
        return (
            self.get_composition_run(UUID(str(run_id)), project_id, owner_id)
            if run_id is not None
            else None
        )

    def create_composition_run(
        self,
        *,
        workflow_version_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        profile: RenderProfile,
        cache_key: str,
        idempotency_key: str,
    ) -> CompositionRun:
        run_id = uuid4()
        now = utc_now()
        try:
            with self._engine.begin() as connection:
                self._require_workflow_version(
                    connection, workflow_version_id, project_id, owner_id
                )
                connection.execute(
                    text(
                        "INSERT INTO workflow_composition_runs "
                        "(id,workflow_version_id,project_id,owner_id,profile,cache_key,"
                        "idempotency_key,created_at) VALUES "
                        "(:id,:workflow_version_id,:project_id,:owner_id,:profile,:cache_key,"
                        ":idempotency_key,:created_at)"
                    ),
                    {
                        "id": str(run_id),
                        "workflow_version_id": str(workflow_version_id),
                        "project_id": str(project_id),
                        "owner_id": str(owner_id),
                        "profile": profile.value,
                        "cache_key": cache_key,
                        "idempotency_key": idempotency_key,
                        "created_at": now.isoformat(),
                    },
                )
                self._insert_composition_event(
                    connection,
                    run_id=run_id,
                    owner_id=owner_id,
                    state_version=0,
                    status=CompositionRunStatus.QUEUED,
                )
        except (IntegrityError, OperationalError) as error:
            self._raise_conflict(error)
        return self.get_composition_run(run_id, project_id, owner_id)

    def append_composition_run_event(
        self,
        *,
        run_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        expected_state_version: int,
        status: CompositionRunStatus,
        manifest: CompositionManifest | None = None,
        artifact_id: UUID | None = None,
        error_code: str | None = None,
    ) -> CompositionRun:
        try:
            with self._engine.begin() as connection:
                current = self._require_composition_run(
                    connection, run_id, project_id, owner_id
                )
                if int(current["state_version"]) != expected_state_version:
                    raise WORKFLOW_VERSION_CONFLICT
                self._insert_composition_event(
                    connection,
                    run_id=run_id,
                    owner_id=owner_id,
                    state_version=expected_state_version + 1,
                    status=status,
                    manifest=manifest,
                    artifact_id=artifact_id,
                    error_code=error_code,
                )
        except (IntegrityError, OperationalError) as error:
            self._raise_conflict(error)
        return self.get_composition_run(run_id, project_id, owner_id)

    def get_composition_run(
        self, run_id: UUID, project_id: UUID, owner_id: UUID
    ) -> CompositionRun:
        with self._engine.connect() as connection:
            row = self._require_composition_run(connection, run_id, project_id, owner_id)
        return self._composition_from_row(row)

    def find_composition_run_by_idempotency(
        self, idempotency_key: str, project_id: UUID, owner_id: UUID
    ) -> CompositionRun | None:
        with self._engine.connect() as connection:
            run_id = connection.execute(
                text(
                    "SELECT id FROM workflow_composition_runs WHERE idempotency_key=:key "
                    "AND project_id=:project_id AND owner_id=:owner_id"
                ),
                {
                    "key": idempotency_key,
                    "project_id": str(project_id),
                    "owner_id": str(owner_id),
                },
            ).scalar_one_or_none()
        return (
            self.get_composition_run(UUID(str(run_id)), project_id, owner_id)
            if run_id is not None
            else None
        )

    def get_composition_clip_rows(
        self, workflow: VideoWorkflowVersion, profile: RenderProfile
    ) -> tuple[dict[str, object], ...] | None:
        artifact_column = (
            "preview_artifact_id" if profile is RenderProfile.PREVIEW else "final_artifact_id"
        )
        scene_ids = tuple(
            node.scene_block_version_id
            for node in workflow.nodes
            if node.kind.value == "scene"
        )
        rows: list[dict[str, object]] = []
        with self._engine.connect() as connection:
            for scene_id in scene_ids:
                row = (
                    connection.execute(
                        text(
                            f"SELECT a.id AS artifact_id,a.sha256,a.byte_size,a.relative_path,"
                            f"a.duration_seconds,e.intent_ref,e.animation_ir_ref,"
                            f"e.compiled_program_ref FROM scene_block_runs r "
                            f"JOIN scene_block_run_events e ON e.run_id=r.id "
                            f"JOIN workflow_artifacts a ON a.id=e.{artifact_column} "
                            f"WHERE r.scene_block_version_id=:scene_id "
                            f"AND r.project_id=:project_id AND r.owner_id=:owner_id "
                            f"AND e.status='succeeded' AND e.state_version=(SELECT MAX(latest."
                            f"state_version) FROM scene_block_run_events latest "
                            f"WHERE latest.run_id=r.id) AND a.project_id=:project_id "
                            f"AND a.owner_id=:owner_id ORDER BY r.created_at DESC LIMIT 1"
                        ),
                        {
                            "scene_id": str(scene_id),
                            "project_id": str(workflow.project_id),
                            "owner_id": str(workflow.owner_id),
                        },
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    return None
                rows.append(
                    {
                        "scene_block_version_id": scene_id,
                        "artifact_id": UUID(str(row["artifact_id"])),
                        "sha256": str(row["sha256"]),
                        "byte_size": int(row["byte_size"]),
                        "relative_path": str(row["relative_path"]),
                        "duration_seconds": float(row["duration_seconds"]),
                        "intent_ref": _uuid(row["intent_ref"]),
                        "animation_ir_ref": _uuid(row["animation_ir_ref"]),
                        "compiled_program_ref": _uuid(row["compiled_program_ref"]),
                    }
                )
        return tuple(rows)

    def find_scene_cache_artifact(
        self,
        cache_key: str,
        project_id: UUID,
        owner_id: UUID,
        profile: RenderProfile,
    ) -> CacheArtifactDescriptor | None:
        artifact_column = (
            "preview_artifact_id" if profile is RenderProfile.PREVIEW else "final_artifact_id"
        )
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        f"SELECT a.owner_id,a.project_id,a.relative_path,a.sha256,a.byte_size "
                        f"FROM scene_block_runs r JOIN projects p ON p.id=r.project_id "
                        f"JOIN scene_block_run_events e ON e.run_id=r.id "
                        f"JOIN workflow_artifacts a ON a.id=e.{artifact_column} "
                        f"WHERE r.cache_key=:cache_key AND r.project_id=:project_id "
                        f"AND r.owner_id=:owner_id AND p.owner_id=:owner_id "
                        f"AND p.archived_at IS NULL AND e.status='succeeded' "
                        f"AND e.state_version=(SELECT MAX(latest.state_version) "
                        f"FROM scene_block_run_events latest WHERE latest.run_id=r.id) "
                        f"AND a.project_id=:project_id AND a.owner_id=:owner_id "
                        f"ORDER BY r.created_at DESC LIMIT 1"
                    ),
                    {
                        "cache_key": cache_key,
                        "project_id": str(project_id),
                        "owner_id": str(owner_id),
                    },
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return CacheArtifactDescriptor(
            owner_id=UUID(str(row["owner_id"])),
            project_id=UUID(str(row["project_id"])),
            profile=profile,
            relative_path=str(row["relative_path"]),
            sha256=str(row["sha256"]),
            byte_size=int(row["byte_size"]),
        )

    @staticmethod
    def _require_active_project(
        connection: Connection, project_id: UUID, owner_id: UUID
    ) -> None:
        row = connection.execute(
            text(
                "SELECT id FROM projects WHERE id=:project_id AND owner_id=:owner_id "
                "AND archived_at IS NULL"
            ),
            {"project_id": str(project_id), "owner_id": str(owner_id)},
        ).one_or_none()
        if row is None:
            raise WORKFLOW_NOT_FOUND

    def _require_workflow(
        self, connection: Connection, workflow_id: UUID, project_id: UUID, owner_id: UUID
    ) -> None:
        self._require_active_project(connection, project_id, owner_id)
        row = connection.execute(
            text(
                "SELECT id FROM video_workflows WHERE id=:id AND project_id=:project_id "
                "AND owner_id=:owner_id"
            ),
            self._scope_values(workflow_id, project_id, owner_id),
        ).one_or_none()
        if row is None:
            raise WORKFLOW_NOT_FOUND

    def _current_scene_parent(
        self, connection: Connection, parent_id: UUID, project_id: UUID, owner_id: UUID
    ) -> Any:
        self._require_active_project(connection, project_id, owner_id)
        parent = (
            connection.execute(
                text(
                    "SELECT v.id,v.scene_block_id,v.workflow_id,v.version FROM "
                    "scene_block_versions v WHERE v.id=:id AND v.project_id=:project_id "
                    "AND v.owner_id=:owner_id AND NOT EXISTS (SELECT 1 FROM "
                    "scene_block_versions newer WHERE newer.scene_block_id=v.scene_block_id "
                    "AND newer.version>v.version)"
                ),
                self._scope_values(parent_id, project_id, owner_id),
            )
            .mappings()
            .one_or_none()
        )
        if parent is None:
            raise WORKFLOW_VERSION_CONFLICT
        return parent

    @staticmethod
    def _require_assets(
        connection: Connection,
        asset_ids: tuple[UUID, ...],
        project_id: UUID,
        owner_id: UUID,
    ) -> None:
        for asset_id in asset_ids:
            row = connection.execute(
                text(
                    "SELECT id FROM workflow_asset_versions WHERE id=:id "
                    "AND project_id=:project_id AND owner_id=:owner_id UNION ALL "
                    "SELECT a.id FROM asset_versions a JOIN asset_version_scopes s "
                    "ON s.asset_version_id=a.id WHERE a.id=:id "
                    "AND s.project_id=:project_id AND s.owner_id=:owner_id LIMIT 1"
                ),
                {"id": str(asset_id), "project_id": str(project_id), "owner_id": str(owner_id)},
            ).one_or_none()
            if row is None:
                raise WORKFLOW_REFERENCE_INVALID

    @staticmethod
    def _require_scene_references(
        connection: Connection,
        nodes: tuple[WorkflowNode, ...],
        workflow_id: UUID,
        project_id: UUID,
        owner_id: UUID,
    ) -> tuple[SceneBlockVersion, ...]:
        resolved: list[SceneBlockVersion] = []
        for node in nodes:
            if node.scene_block_version_id is None:
                continue
            row = (
                connection.execute(
                text(
                    "SELECT * FROM scene_block_versions WHERE id=:id "
                    "AND workflow_id=:workflow_id AND project_id=:project_id "
                    "AND owner_id=:owner_id"
                ),
                {
                    "id": str(node.scene_block_version_id),
                    "workflow_id": str(workflow_id),
                    "project_id": str(project_id),
                    "owner_id": str(owner_id),
                },
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise WORKFLOW_REFERENCE_INVALID
            resolved.append(WorkflowRepository._scene_from_row(row))
        return tuple(resolved)

    @staticmethod
    def _require_workflow_version(
        connection: Connection, version_id: UUID, project_id: UUID, owner_id: UUID
    ) -> None:
        row = connection.execute(
            text(
                "SELECT v.id FROM video_workflow_versions v JOIN projects p ON p.id=v.project_id "
                "WHERE v.id=:id AND v.project_id=:project_id AND v.owner_id=:owner_id "
                "AND p.owner_id=:owner_id AND p.archived_at IS NULL"
            ),
            WorkflowRepository._scope_values(version_id, project_id, owner_id),
        ).one_or_none()
        if row is None:
            raise WORKFLOW_NOT_FOUND

    def _require_run_references(
        self,
        connection: Connection,
        scene_version_id: UUID,
        workflow_version_id: UUID,
        project_id: UUID,
        owner_id: UUID,
    ) -> None:
        self._require_workflow_version(connection, workflow_version_id, project_id, owner_id)
        row = connection.execute(
            text(
                "SELECT s.id FROM scene_block_versions s JOIN video_workflow_versions w "
                "ON w.id=:workflow_version_id AND w.workflow_id=s.workflow_id "
                "WHERE s.id=:scene_version_id AND s.project_id=:project_id "
                "AND s.owner_id=:owner_id"
            ),
            {
                "workflow_version_id": str(workflow_version_id),
                "scene_version_id": str(scene_version_id),
                "project_id": str(project_id),
                "owner_id": str(owner_id),
            },
        ).one_or_none()
        if row is None:
            raise WORKFLOW_REFERENCE_INVALID

    @staticmethod
    def _require_scene_run(
        connection: Connection, run_id: UUID, project_id: UUID, owner_id: UUID
    ) -> Any:
        row = (
            connection.execute(
                text(
                    "SELECT r.*,e.state_version,e.status,e.pipeline_used,e.intent_ref,"
                    "e.animation_ir_ref,e.compiled_program_ref,e.preview_artifact_id,"
                    "e.final_artifact_id,e.error_code FROM scene_block_runs r "
                    "JOIN projects p ON p.id=r.project_id "
                    "JOIN scene_block_run_events e ON e.run_id=r.id "
                    "WHERE r.id=:id AND r.project_id=:project_id AND r.owner_id=:owner_id "
                    "AND p.owner_id=:owner_id AND p.archived_at IS NULL "
                    "ORDER BY e.state_version DESC LIMIT 1"
                ),
                WorkflowRepository._scope_values(run_id, project_id, owner_id),
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise WORKFLOW_NOT_FOUND
        return row

    @staticmethod
    def _require_composition_run(
        connection: Connection, run_id: UUID, project_id: UUID, owner_id: UUID
    ) -> Any:
        row = (
            connection.execute(
                text(
                    "SELECT r.*,e.state_version,e.status,e.manifest_json,e.artifact_id,"
                    "e.error_code FROM workflow_composition_runs r "
                    "JOIN projects p ON p.id=r.project_id "
                    "JOIN workflow_composition_run_events e ON e.run_id=r.id "
                    "WHERE r.id=:id AND r.project_id=:project_id AND r.owner_id=:owner_id "
                    "AND p.owner_id=:owner_id AND p.archived_at IS NULL "
                    "ORDER BY e.state_version DESC LIMIT 1"
                ),
                WorkflowRepository._scope_values(run_id, project_id, owner_id),
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise WORKFLOW_NOT_FOUND
        return row

    @staticmethod
    def _insert_scene_version(
        connection: Connection, scene_block_id: UUID, record: SceneBlockVersion
    ) -> None:
        connection.execute(
            text(
                "INSERT INTO scene_block_versions "
                "(id,scene_block_id,workflow_id,project_id,owner_id,version,parent_version_id,"
                "title,prompt,pipeline_mode,target_duration_seconds,asset_version_ids_json,"
                "created_at) VALUES (:id,:scene_block_id,:workflow_id,:project_id,:owner_id,"
                ":version,:parent_version_id,:title,:prompt,:pipeline_mode,:duration,:assets,"
                ":created_at)"
            ),
            {
                "id": str(record.id),
                "scene_block_id": str(scene_block_id),
                "workflow_id": str(record.workflow_id),
                "project_id": str(record.project_id),
                "owner_id": str(record.owner_id),
                "version": record.version,
                "parent_version_id": (
                    str(record.parent_version_id) if record.parent_version_id else None
                ),
                "title": record.title,
                "prompt": record.prompt,
                "pipeline_mode": record.pipeline_mode.value,
                "duration": record.target_duration_seconds,
                "assets": json.dumps([str(item) for item in record.asset_version_ids]),
                "created_at": record.created_at.isoformat(),
            },
        )

    @staticmethod
    def _insert_scene_event(
        connection: Connection,
        *,
        run_id: UUID,
        owner_id: UUID,
        state_version: int,
        status: SceneBlockRunStatus,
        pipeline_used: ScenePipeline | None = None,
        intent_ref: UUID | None = None,
        animation_ir_ref: UUID | None = None,
        compiled_program_ref: UUID | None = None,
        preview_artifact_id: UUID | None = None,
        final_artifact_id: UUID | None = None,
        error_code: str | None = None,
    ) -> None:
        connection.execute(
            text(
                "INSERT INTO scene_block_run_events "
                "(id,run_id,owner_id,state_version,status,pipeline_used,intent_ref,"
                "animation_ir_ref,compiled_program_ref,preview_artifact_id,final_artifact_id,"
                "error_code,created_at) VALUES (:id,:run_id,:owner_id,:state_version,:status,"
                ":pipeline_used,:intent_ref,:animation_ir_ref,:compiled_program_ref,"
                ":preview_artifact_id,:final_artifact_id,:error_code,:created_at)"
            ),
            {
                "id": str(uuid4()),
                "run_id": str(run_id),
                "owner_id": str(owner_id),
                "state_version": state_version,
                "status": status.value,
                "pipeline_used": pipeline_used.value if pipeline_used else None,
                "intent_ref": str(intent_ref) if intent_ref else None,
                "animation_ir_ref": str(animation_ir_ref) if animation_ir_ref else None,
                "compiled_program_ref": str(compiled_program_ref) if compiled_program_ref else None,
                "preview_artifact_id": str(preview_artifact_id) if preview_artifact_id else None,
                "final_artifact_id": str(final_artifact_id) if final_artifact_id else None,
                "error_code": error_code,
                "created_at": utc_now().isoformat(),
            },
        )

    @staticmethod
    def _insert_composition_event(
        connection: Connection,
        *,
        run_id: UUID,
        owner_id: UUID,
        state_version: int,
        status: CompositionRunStatus,
        manifest: CompositionManifest | None = None,
        artifact_id: UUID | None = None,
        error_code: str | None = None,
    ) -> None:
        connection.execute(
            text(
                "INSERT INTO workflow_composition_run_events "
                "(id,run_id,owner_id,state_version,status,manifest_json,artifact_id,error_code,"
                "created_at) VALUES (:id,:run_id,:owner_id,:state_version,:status,:manifest,"
                ":artifact_id,:error_code,:created_at)"
            ),
            {
                "id": str(uuid4()),
                "run_id": str(run_id),
                "owner_id": str(owner_id),
                "state_version": state_version,
                "status": status.value,
                "manifest": manifest.model_dump_json() if manifest else None,
                "artifact_id": str(artifact_id) if artifact_id else None,
                "error_code": error_code,
                "created_at": utc_now().isoformat(),
            },
        )

    @staticmethod
    def _scene_from_row(row: Any) -> SceneBlockVersion:
        return SceneBlockVersion(
            id=UUID(str(row["id"])),
            workflow_id=UUID(str(row["workflow_id"])),
            project_id=UUID(str(row["project_id"])),
            owner_id=UUID(str(row["owner_id"])),
            version=int(row["version"]),
            parent_version_id=_uuid(row["parent_version_id"]),
            title=str(row["title"]),
            prompt=str(row["prompt"]),
            pipeline_mode=ScenePipelineMode(str(row["pipeline_mode"])),
            target_duration_seconds=int(row["target_duration_seconds"]),
            asset_version_ids=tuple(
                UUID(item) for item in json.loads(row["asset_version_ids_json"])
            ),
            created_at=_datetime(row["created_at"]),
        )

    @staticmethod
    def _workflow_from_row(row: Any) -> VideoWorkflowVersion:
        return VideoWorkflowVersion(
            id=UUID(str(row["id"])),
            workflow_id=UUID(str(row["workflow_id"])),
            project_id=UUID(str(row["project_id"])),
            owner_id=UUID(str(row["owner_id"])),
            version=int(row["version"]),
            parent_version_id=_uuid(row["parent_version_id"]),
            global_brief=GlobalBrief.model_validate_json(row["global_brief_json"]),
            nodes=_NODES.validate_json(row["nodes_json"]),
            edges=_EDGES.validate_json(row["edges_json"]),
            created_at=_datetime(row["created_at"]),
        )

    @staticmethod
    def _scene_run_from_row(row: Any) -> SceneBlockRun:
        return SceneBlockRun(
            id=UUID(str(row["id"])),
            project_id=UUID(str(row["project_id"])),
            owner_id=UUID(str(row["owner_id"])),
            scene_block_version_id=UUID(str(row["scene_block_version_id"])),
            profile=RenderProfile(str(row["profile"])),
            status=SceneBlockRunStatus(str(row["status"])),
            pipeline_used=(
                ScenePipeline(str(row["pipeline_used"])) if row["pipeline_used"] else None
            ),
            intent_ref=_uuid(row["intent_ref"]),
            animation_ir_ref=_uuid(row["animation_ir_ref"]),
            compiled_program_ref=_uuid(row["compiled_program_ref"]),
            preview_artifact_id=_uuid(row["preview_artifact_id"]),
            final_artifact_id=_uuid(row["final_artifact_id"]),
            cache_key=str(row["cache_key"]),
            error_code=str(row["error_code"]) if row["error_code"] else None,
            state_version=int(row["state_version"]),
            created_at=_datetime(row["created_at"]),
        )

    @staticmethod
    def _composition_from_row(row: Any) -> CompositionRun:
        return CompositionRun(
            id=UUID(str(row["id"])),
            workflow_version_id=UUID(str(row["workflow_version_id"])),
            project_id=UUID(str(row["project_id"])),
            owner_id=UUID(str(row["owner_id"])),
            profile=RenderProfile(str(row["profile"])),
            status=CompositionRunStatus(str(row["status"])),
            cache_key=str(row["cache_key"]),
            manifest=(
                CompositionManifest.model_validate_json(row["manifest_json"])
                if row["manifest_json"]
                else None
            ),
            artifact_id=_uuid(row["artifact_id"]),
            error_code=str(row["error_code"]) if row["error_code"] else None,
            state_version=int(row["state_version"]),
            created_at=_datetime(row["created_at"]),
        )

    @staticmethod
    def _identity_values(
        identity: UUID, project_id: UUID, owner_id: UUID, created_at: datetime
    ) -> dict[str, object]:
        return {
            "id": str(identity),
            "project_id": str(project_id),
            "owner_id": str(owner_id),
            "created_at": created_at.isoformat(),
        }

    @staticmethod
    def _scope_values(
        identity: UUID, project_id: UUID, owner_id: UUID
    ) -> dict[str, str]:
        return {"id": str(identity), "project_id": str(project_id), "owner_id": str(owner_id)}

    @staticmethod
    def _raise_conflict(error: IntegrityError | OperationalError) -> None:
        if isinstance(error, IntegrityError) or "locked" in str(error).lower():
            raise WORKFLOW_VERSION_CONFLICT from error
        raise error
