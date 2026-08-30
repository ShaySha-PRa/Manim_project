"""Owner-scoped durable persistence for workflow Director plans."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from manim_workbench_contracts import (
    DirectorDraft,
    DirectorPlan,
    DirectorPlanRequest,
    DirectorPlanStatus,
    GlobalBrief,
    SceneBlockVersion,
    VideoWorkflowVersion,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeKind,
)
from sqlalchemy import Engine, text

from manim_workbench_api.workflows.repository import WorkflowRepository
from manim_workbench_api.workflows.validation import validate_linear_workflow


class DirectorPlanNotFound(ValueError):
    """The scoped Director plan/project/asset boundary was not found."""


@dataclass(frozen=True, slots=True)
class DirectorAttempt:
    id: UUID
    plan_id: UUID
    owner_id: UUID
    attempt_number: int
    status: str
    provider_model: str | None
    provider_request_id: str | None
    prompt_template_version: str
    prompt_sha256: str
    prompt_tokens: int | None
    completion_tokens: int | None
    candidate_sha256: str | None
    diagnostic_sha256: str | None
    error_code: str | None
    created_at: datetime


_TRANSITIONS = {
    DirectorPlanStatus.QUEUED: {
        DirectorPlanStatus.PLANNING,
        DirectorPlanStatus.CANCELLED,
        DirectorPlanStatus.FAILED,
    },
    DirectorPlanStatus.PLANNING: {
        DirectorPlanStatus.READY,
        DirectorPlanStatus.NEEDS_CONFIRMATION,
        DirectorPlanStatus.FAILED,
        DirectorPlanStatus.CANCELLED,
    },
    DirectorPlanStatus.READY: set(),
    DirectorPlanStatus.NEEDS_CONFIRMATION: set(),
    DirectorPlanStatus.FAILED: set(),
    DirectorPlanStatus.CANCELLED: set(),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DirectorRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_or_get(
        self,
        request: DirectorPlanRequest,
        *,
        owner_id: UUID,
        cache_key: str,
        input_sha256: str,
        prompt_template_version: str,
    ) -> tuple[DirectorPlan, bool]:
        now = _now()
        with self._engine.begin() as connection:
            self._require_project(connection, request.project_id, owner_id)
            self._require_assets(
                connection, request.asset_version_ids, request.project_id, owner_id
            )
            existing = (
                connection.execute(
                    text(
                        "SELECT * FROM workflow_director_plans "
                        "WHERE owner_id=:owner AND idempotency_key=:key"
                    ),
                    {"owner": str(owner_id), "key": request.idempotency_key},
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                replay = self._from_plan_row(existing)
                if (
                    replay.project_id != request.project_id
                    or replay.request != request
                    or replay.cache_key != cache_key
                    or replay.input_sha256 != input_sha256
                    or replay.prompt_template_version != prompt_template_version
                ):
                    raise ValueError("director plan idempotency conflict")
                return replay, False
            plan_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO workflow_director_plans "
                    "(id,project_id,owner_id,status,request_json,draft_json,cache_key,"
                    "idempotency_key,input_sha256,output_sha256,attempt_count,provider_model,"
                    "prompt_template_version,error_code,state_version,created_at,updated_at) "
                    "VALUES (:id,:project,:owner,'queued',:request,NULL,:cache,:key,:input,NULL,"
                    "0,NULL,:template,NULL,0,:now,:now)"
                ),
                {
                    "id": str(plan_id),
                    "project": str(request.project_id),
                    "owner": str(owner_id),
                    "request": request.model_dump_json(),
                    "cache": cache_key,
                    "key": request.idempotency_key,
                    "input": input_sha256,
                    "template": prompt_template_version,
                    "now": now.isoformat(),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO workflow_director_events "
                    "(id,plan_id,owner_id,state_version,status,error_code,created_at) "
                    "VALUES (:id,:plan,:owner,0,'queued',NULL,:now)"
                ),
                {
                    "id": str(uuid4()),
                    "plan": str(plan_id),
                    "owner": str(owner_id),
                    "now": now.isoformat(),
                },
            )
            row = connection.execute(
                text("SELECT * FROM workflow_director_plans WHERE id=:id"),
                {"id": str(plan_id)},
            ).mappings().one()
        return self._from_plan_row(row), True

    def get(self, plan_id: UUID, project_id: UUID, owner_id: UUID) -> DirectorPlan:
        with self._engine.connect() as connection:
            row = self._scoped_row(connection, plan_id, project_id, owner_id)
        if row is None:
            raise DirectorPlanNotFound("director plan was not found")
        return self._from_plan_row(row)

    def transition(
        self,
        plan_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        *,
        expected_state_version: int,
        status: DirectorPlanStatus,
        draft: DirectorDraft | None = None,
        output_sha256: str | None = None,
        attempt_count: int | None = None,
        provider_model: str | None = None,
        error_code: str | None = None,
    ) -> DirectorPlan:
        now = _now()
        with self._engine.begin() as connection:
            row = self._scoped_row(connection, plan_id, project_id, owner_id)
            if row is None:
                raise DirectorPlanNotFound("director plan was not found")
            current = DirectorPlanStatus(str(row["status"]))
            if int(row["state_version"]) != expected_state_version:
                raise ValueError("stale director plan state")
            if status not in _TRANSITIONS[current]:
                raise ValueError("invalid director plan transition")
            values = {
                "id": str(plan_id),
                "owner": str(owner_id),
                "project": str(project_id),
                "expected": expected_state_version,
                "status": status.value,
                "draft": draft.model_dump_json() if draft is not None else None,
                "output": output_sha256,
                "attempt_count": (
                    attempt_count if attempt_count is not None else row["attempt_count"]
                ),
                "provider": provider_model if provider_model is not None else row["provider_model"],
                "error": error_code,
                "now": now.isoformat(),
            }
            changed = connection.execute(
                text(
                    "UPDATE workflow_director_plans SET status=:status,draft_json=:draft,"
                    "output_sha256=:output,attempt_count=:attempt_count,provider_model=:provider,"
                    "error_code=:error,state_version=state_version+1,updated_at=:now "
                    "WHERE id=:id AND project_id=:project AND owner_id=:owner "
                    "AND state_version=:expected"
                ),
                values,
            ).rowcount
            if changed != 1:
                raise ValueError("stale director plan state")
            connection.execute(
                text(
                    "INSERT INTO workflow_director_events "
                    "(id,plan_id,owner_id,state_version,status,error_code,created_at) "
                    "VALUES (:event,:id,:owner,:state,:status,:error,:now)"
                ),
                {**values, "event": str(uuid4()), "state": expected_state_version + 1},
            )
            updated = connection.execute(
                text("SELECT * FROM workflow_director_plans WHERE id=:id"),
                {"id": str(plan_id)},
            ).mappings().one()
        return self._from_plan_row(updated)

    def append_attempt(self, attempt: DirectorAttempt) -> None:
        with self._engine.begin() as connection:
            boundary = connection.execute(
                text(
                    "SELECT 1 FROM workflow_director_plans "
                    "WHERE id=:plan AND owner_id=:owner"
                ),
                {"plan": str(attempt.plan_id), "owner": str(attempt.owner_id)},
            ).one_or_none()
            if boundary is None:
                raise DirectorPlanNotFound("director plan was not found")
            connection.execute(
                text(
                    "INSERT INTO workflow_director_attempts "
                    "(id,plan_id,owner_id,attempt_number,status,provider_model,"
                    "provider_request_id,prompt_template_version,prompt_sha256,prompt_tokens,"
                    "completion_tokens,candidate_sha256,diagnostic_sha256,error_code,created_at) "
                    "VALUES (:id,:plan,:owner,:number,:status,:provider,:request,:template,"
                    ":prompt_sha,:prompt_tokens,:completion_tokens,:candidate,:diagnostic,"
                    ":error,:created)"
                ),
                self._attempt_values(attempt),
            )

    def list_attempts(self, plan_id: UUID, owner_id: UUID) -> tuple[DirectorAttempt, ...]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT * FROM workflow_director_attempts "
                        "WHERE plan_id=:plan AND owner_id=:owner ORDER BY attempt_number"
                    ),
                    {"plan": str(plan_id), "owner": str(owner_id)},
                )
                .mappings()
                .all()
            )
        return tuple(self._attempt_from_row(row) for row in rows)

    def apply(
        self,
        plan_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        *,
        draft: DirectorDraft,
        scene_asset_version_ids: tuple[tuple[UUID, ...], ...],
        idempotency_key: str,
    ) -> VideoWorkflowVersion:
        if len(scene_asset_version_ids) != len(draft.scenes):
            raise ValueError("Director apply asset bindings must match scene count")
        now = _now()
        with self._engine.begin() as connection:
            row = self._scoped_row(connection, plan_id, project_id, owner_id)
            if row is None:
                raise DirectorPlanNotFound("director plan was not found")
            plan = self._from_plan_row(row)
            if plan.status is not DirectorPlanStatus.READY:
                raise ValueError("director plan is not ready to apply")
            existing = (
                connection.execute(
                    text(
                        "SELECT * FROM video_workflow_versions "
                        "WHERE director_plan_id=:plan AND project_id=:project "
                        "AND owner_id=:owner LIMIT 1"
                    ),
                    {
                        "plan": str(plan_id),
                        "project": str(project_id),
                        "owner": str(owner_id),
                    },
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                metadata = json.loads(str(existing["director_edits_json"]))
                if metadata.get("idempotency_key") != idempotency_key:
                    raise ValueError("director apply idempotency conflict")
                return WorkflowRepository._workflow_from_row(existing)

            self._require_project(connection, project_id, owner_id)
            workflow_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO video_workflows (id,project_id,owner_id,created_at) "
                    "VALUES (:id,:project,:owner,:now)"
                ),
                {
                    "id": str(workflow_id),
                    "project": str(project_id),
                    "owner": str(owner_id),
                    "now": now.isoformat(),
                },
            )
            scene_versions: list[SceneBlockVersion] = []
            for scene, asset_ids in zip(
                draft.scenes, scene_asset_version_ids, strict=True
            ):
                self._require_assets(connection, asset_ids, project_id, owner_id)
                block_id = uuid4()
                version = SceneBlockVersion(
                    id=uuid4(),
                    workflow_id=workflow_id,
                    project_id=project_id,
                    owner_id=owner_id,
                    version=1,
                    parent_version_id=None,
                    title=scene.title,
                    prompt=scene.prompt,
                    pipeline_mode=scene.pipeline_mode,
                    target_duration_seconds=scene.target_duration_seconds,
                    asset_version_ids=asset_ids,
                    created_at=now,
                )
                connection.execute(
                    text(
                        "INSERT INTO scene_blocks "
                        "(id,workflow_id,project_id,owner_id,created_at) "
                        "VALUES (:id,:workflow,:project,:owner,:now)"
                    ),
                    {
                        "id": str(block_id),
                        "workflow": str(workflow_id),
                        "project": str(project_id),
                        "owner": str(owner_id),
                        "now": now.isoformat(),
                    },
                )
                WorkflowRepository._insert_scene_version(connection, block_id, version)
                scene_versions.append(version)

            node_ids = tuple(uuid4() for _ in range(len(scene_versions) + 2))
            nodes = tuple(
                WorkflowNode(
                    id=node_ids[index],
                    kind=WorkflowNodeKind.SCENE,
                    scene_block_version_id=scene.id,
                )
                for index, scene in enumerate(scene_versions)
            ) + (
                WorkflowNode(id=node_ids[-2], kind=WorkflowNodeKind.COMPOSE),
                WorkflowNode(id=node_ids[-1], kind=WorkflowNodeKind.EXPORT),
            )
            edges = tuple(
                WorkflowEdge(
                    source_node_id=node_ids[index],
                    target_node_id=node_ids[index + 1],
                )
                for index in range(len(node_ids) - 1)
            )
            brief = GlobalBrief.model_validate(draft.global_brief.model_dump())
            validate_linear_workflow(
                global_brief=brief,
                nodes=nodes,
                edges=edges,
                scene_versions=tuple(scene_versions),
            )
            original_sha = plan.output_sha256 or ""
            applied_sha = __import__("hashlib").sha256(
                draft.model_dump_json().encode("utf-8")
            ).hexdigest()
            edits = json.dumps(
                {
                    "applied_sha256": applied_sha,
                    "changed": original_sha != applied_sha,
                    "idempotency_key": idempotency_key,
                    "original_sha256": original_sha,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            record = VideoWorkflowVersion(
                id=uuid4(),
                workflow_id=workflow_id,
                project_id=project_id,
                owner_id=owner_id,
                version=1,
                parent_version_id=None,
                global_brief=brief,
                nodes=nodes,
                edges=edges,
                created_at=now,
            )
            connection.execute(
                text(
                    "INSERT INTO video_workflow_versions "
                    "(id,workflow_id,project_id,owner_id,version,parent_version_id,"
                    "global_brief_json,nodes_json,edges_json,director_plan_id,"
                    "director_edits_json,created_at) VALUES "
                    "(:id,:workflow,:project,:owner,1,NULL,:brief,:nodes,:edges,:plan,:edits,:now)"
                ),
                {
                    "id": str(record.id),
                    "workflow": str(workflow_id),
                    "project": str(project_id),
                    "owner": str(owner_id),
                    "brief": brief.model_dump_json(),
                    "nodes": json.dumps(
                        [item.model_dump(mode="json") for item in nodes], default=str
                    ),
                    "edges": json.dumps(
                        [item.model_dump(mode="json") for item in edges], default=str
                    ),
                    "plan": str(plan_id),
                    "edits": edits,
                    "now": now.isoformat(),
                },
            )
        return record

    @staticmethod
    def _require_project(connection: Any, project_id: UUID, owner_id: UUID) -> None:
        found = connection.execute(
            text(
                "SELECT 1 FROM projects WHERE id=:project AND owner_id=:owner "
                "AND archived_at IS NULL"
            ),
            {"project": str(project_id), "owner": str(owner_id)},
        ).one_or_none()
        if found is None:
            raise DirectorPlanNotFound("director project was not found")

    @staticmethod
    def _require_assets(
        connection: Any, asset_ids: tuple[UUID, ...], project_id: UUID, owner_id: UUID
    ) -> None:
        for asset_id in asset_ids:
            found = connection.execute(
                text(
                    "SELECT id FROM workflow_asset_versions WHERE id=:asset "
                    "AND project_id=:project AND owner_id=:owner "
                    "UNION ALL SELECT asset_version_id FROM asset_version_scopes "
                    "WHERE asset_version_id=:asset AND project_id=:project AND owner_id=:owner"
                ),
                {
                    "asset": str(asset_id),
                    "project": str(project_id),
                    "owner": str(owner_id),
                },
            ).one_or_none()
            if found is None:
                raise DirectorPlanNotFound("director asset was not found")

    @staticmethod
    def _scoped_row(
        connection: Any, plan_id: UUID, project_id: UUID, owner_id: UUID
    ) -> Any | None:
        return (
            connection.execute(
                text(
                    "SELECT d.* FROM workflow_director_plans d "
                    "JOIN projects p ON p.id=d.project_id "
                    "WHERE d.id=:id AND d.project_id=:project AND d.owner_id=:owner "
                    "AND p.owner_id=:owner AND p.archived_at IS NULL"
                ),
                {"id": str(plan_id), "project": str(project_id), "owner": str(owner_id)},
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _from_plan_row(row: Any) -> DirectorPlan:
        return DirectorPlan(
            id=UUID(str(row["id"])),
            project_id=UUID(str(row["project_id"])),
            owner_id=UUID(str(row["owner_id"])),
            request=DirectorPlanRequest.model_validate_json(str(row["request_json"])),
            status=DirectorPlanStatus(str(row["status"])),
            draft=(
                DirectorDraft.model_validate_json(str(row["draft_json"]))
                if row["draft_json"] is not None
                else None
            ),
            cache_key=str(row["cache_key"]),
            attempt_count=int(row["attempt_count"]),
            provider_model=str(row["provider_model"]) if row["provider_model"] else None,
            prompt_template_version=str(row["prompt_template_version"]),
            input_sha256=str(row["input_sha256"]),
            output_sha256=str(row["output_sha256"]) if row["output_sha256"] else None,
            error_code=str(row["error_code"]) if row["error_code"] else None,
            state_version=int(row["state_version"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _attempt_values(attempt: DirectorAttempt) -> dict[str, Any]:
        return {
            "id": str(attempt.id),
            "plan": str(attempt.plan_id),
            "owner": str(attempt.owner_id),
            "number": attempt.attempt_number,
            "status": attempt.status,
            "provider": attempt.provider_model,
            "request": attempt.provider_request_id,
            "template": attempt.prompt_template_version,
            "prompt_sha": attempt.prompt_sha256,
            "prompt_tokens": attempt.prompt_tokens,
            "completion_tokens": attempt.completion_tokens,
            "candidate": attempt.candidate_sha256,
            "diagnostic": attempt.diagnostic_sha256,
            "error": attempt.error_code,
            "created": attempt.created_at.isoformat(),
        }

    @staticmethod
    def _attempt_from_row(row: Any) -> DirectorAttempt:
        return DirectorAttempt(
            id=UUID(str(row["id"])),
            plan_id=UUID(str(row["plan_id"])),
            owner_id=UUID(str(row["owner_id"])),
            attempt_number=int(row["attempt_number"]),
            status=str(row["status"]),
            provider_model=str(row["provider_model"]) if row["provider_model"] else None,
            provider_request_id=(
                str(row["provider_request_id"]) if row["provider_request_id"] else None
            ),
            prompt_template_version=str(row["prompt_template_version"]),
            prompt_sha256=str(row["prompt_sha256"]),
            prompt_tokens=int(row["prompt_tokens"]) if row["prompt_tokens"] is not None else None,
            completion_tokens=(
                int(row["completion_tokens"]) if row["completion_tokens"] is not None else None
            ),
            candidate_sha256=str(row["candidate_sha256"]) if row["candidate_sha256"] else None,
            diagnostic_sha256=(
                str(row["diagnostic_sha256"]) if row["diagnostic_sha256"] else None
            ),
            error_code=str(row["error_code"]) if row["error_code"] else None,
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )


__all__ = ["DirectorAttempt", "DirectorPlanNotFound", "DirectorRepository"]
