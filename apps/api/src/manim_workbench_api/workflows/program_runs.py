"""SQLite-authoritative program and segment rendering evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from manim_workbench_contracts import (
    ProgramRenderRun,
    ProgramRenderSegment,
    RenderProfile,
)
from sqlalchemy import Engine, RowMapping, text


class ProgramRenderConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProgramRenderSource:
    source_code: str
    source_sha256: str
    scene_class: str
    target_duration_seconds: float

    def __post_init__(self) -> None:
        if not 1 <= len(self.source_code) <= 200_000:
            raise ValueError("program render source length is invalid")
        if sha256(self.source_code.encode("utf-8")).hexdigest() != self.source_sha256:
            raise ValueError("program render source hash does not match source")
        if re.fullmatch(r"[A-Z][A-Za-z0-9]{1,99}", self.scene_class) is None:
            raise ValueError("program render scene class is invalid")
        if not 0 < self.target_duration_seconds <= 600:
            raise ValueError("program render target duration is invalid")


class ProgramRenderStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_or_get(
        self,
        *,
        scene_block_run_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        profile: RenderProfile,
        program_sha256: str,
        quality_policy: str,
        segment_sources: tuple[ProgramRenderSource, ...],
    ) -> tuple[ProgramRenderRun, tuple[ProgramRenderSegment, ...]]:
        existing = self.find(scene_block_run_id, project_id, owner_id, profile)
        if existing is not None:
            run, segments = existing
            stored_identity = tuple(
                (item.source_sha256, item.scene_class, item.target_duration_seconds)
                for item in segments
            )
            requested_identity = tuple(
                (item.source_sha256, item.scene_class, item.target_duration_seconds)
                for item in segment_sources
            )
            if (
                run.program_sha256 != program_sha256
                or run.quality_policy != quality_policy
                or stored_identity != requested_identity
            ):
                raise ProgramRenderConflict("program render identity differs")
            return existing
        if not segment_sources:
            raise ValueError("program render requires at least one segment")
        now = datetime.now(timezone.utc)
        run_id = uuid4()
        with self._engine.begin() as connection:
            boundary = connection.execute(
                text(
                    "SELECT r.id FROM scene_block_runs r JOIN projects p ON p.id=r.project_id "
                    "WHERE r.id=:run AND r.project_id=:project AND r.owner_id=:owner "
                    "AND p.owner_id=:owner AND p.archived_at IS NULL"
                ),
                {"run": str(scene_block_run_id), "project": str(project_id),
                 "owner": str(owner_id)},
            ).one_or_none()
            if boundary is None:
                raise ValueError("scene block run was not found")
            connection.execute(
                text(
                    "INSERT INTO program_render_runs "
                    "(id,scene_block_run_id,project_id,owner_id,profile,program_sha256,"
                    "quality_policy,status,segment_count,created_at) VALUES "
                    "(:id,:scene,:project,:owner,:profile,:hash,:quality,'compiling',:count,:now)"
                ),
                {"id": str(run_id), "scene": str(scene_block_run_id),
                 "project": str(project_id), "owner": str(owner_id),
                 "profile": profile.value, "hash": program_sha256,
                 "quality": quality_policy, "count": len(segment_sources),
                 "now": now.isoformat()},
            )
            for index, source in enumerate(segment_sources):
                connection.execute(
                    text(
                        "INSERT INTO program_render_segments "
                        "(id,program_render_run_id,segment_index,source_code,source_sha256,"
                        "scene_class,target_duration_seconds,status) "
                        "VALUES (:id,:run,:index,:source,:hash,:scene,:duration,'pending')"
                    ),
                    {"id": str(uuid4()), "run": str(run_id), "index": index,
                     "source": source.source_code, "hash": source.source_sha256,
                     "scene": source.scene_class,
                     "duration": source.target_duration_seconds},
                )
        loaded = self.find(scene_block_run_id, project_id, owner_id, profile)
        assert loaded is not None
        return loaded

    def find(
        self, scene_block_run_id: UUID, project_id: UUID, owner_id: UUID,
        profile: RenderProfile,
    ) -> tuple[ProgramRenderRun, tuple[ProgramRenderSegment, ...]] | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT * FROM program_render_runs WHERE scene_block_run_id=:scene "
                    "AND project_id=:project AND owner_id=:owner AND profile=:profile"
                ),
                {"scene": str(scene_block_run_id), "project": str(project_id),
                 "owner": str(owner_id), "profile": profile.value},
            ).mappings().one_or_none()
            if row is None:
                return None
            segments = connection.execute(
                text(
                    "SELECT * FROM program_render_segments WHERE program_render_run_id=:run "
                    "ORDER BY segment_index"
                ),
                {"run": row["id"]},
            ).mappings().all()
        run = self._run(row)
        loaded_segments = tuple(self._segment(item) for item in segments)
        if (
            len(loaded_segments) != run.segment_count
            or tuple(item.segment_index for item in loaded_segments)
            != tuple(range(run.segment_count))
        ):
            raise ProgramRenderConflict("program render segments are not contiguous")
        return run, loaded_segments

    def load_sources(
        self,
        program_run_id: UUID,
        project_id: UUID,
        owner_id: UUID,
    ) -> tuple[ProgramRenderSource, ...]:
        """Reload the immutable typed sources needed after a Runner restart."""

        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT segments.source_code,segments.source_sha256,"
                        "segments.scene_class,segments.target_duration_seconds "
                        "FROM program_render_segments segments "
                        "JOIN program_render_runs runs "
                        "ON runs.id=segments.program_render_run_id "
                        "WHERE runs.id=:run AND runs.project_id=:project "
                        "AND runs.owner_id=:owner ORDER BY segments.segment_index"
                    ),
                    {
                        "run": str(program_run_id),
                        "project": str(project_id),
                        "owner": str(owner_id),
                    },
                )
                .mappings()
                .all()
            )
        if not rows:
            raise ProgramRenderConflict("program render sources were not found")
        return tuple(
            ProgramRenderSource(
                source_code=str(row["source_code"]),
                source_sha256=str(row["source_sha256"]),
                scene_class=str(row["scene_class"]),
                target_duration_seconds=float(row["target_duration_seconds"]),
            )
            for row in rows
        )

    def attach_job(
        self, program_run_id: UUID, segment_index: int, render_job_id: UUID
    ) -> None:
        with self._engine.begin() as connection:
            identity = connection.execute(
                text(
                    "SELECT segments.id AS segment_id,segments.status,segments.render_job_id,"
                    "runs.project_id,"
                    "runs.owner_id,jobs.code_version_id,jobs.program_render_segment_id,"
                    "versions.source_sha256 AS job_source_sha256,segments.source_sha256,"
                    "jobs.project_id AS job_project_id,jobs.owner_id AS job_owner_id,"
                    "jobs.segment_index AS job_segment_index "
                    "FROM program_render_segments AS segments "
                    "JOIN program_render_runs AS runs "
                    "ON runs.id=segments.program_render_run_id "
                    "JOIN render_jobs AS jobs ON jobs.id=:job "
                    "LEFT JOIN code_versions AS versions ON versions.id=jobs.code_version_id "
                    "WHERE segments.program_render_run_id=:run "
                    "AND segments.segment_index=:index"
                ),
                {"job": str(render_job_id), "run": str(program_run_id),
                 "index": segment_index},
            ).mappings().one_or_none()
            if identity is None:
                raise ProgramRenderConflict("segment or RenderJob was not found")
            typed_source_matches = (
                identity["program_render_segment_id"] == identity["segment_id"]
                and identity["code_version_id"] is None
            )
            teaching_source_matches = (
                identity["code_version_id"] is not None
                and identity["program_render_segment_id"] is None
                and identity["job_source_sha256"] == identity["source_sha256"]
            )
            if (
                not (typed_source_matches or teaching_source_matches)
                or identity["project_id"] != identity["job_project_id"]
                or identity["owner_id"] != identity["job_owner_id"]
                or identity["job_segment_index"] != segment_index
            ):
                raise ProgramRenderConflict("RenderJob typed source identity differs")
            if identity["status"] != "pending":
                if (
                    identity["render_job_id"] == str(render_job_id)
                    and identity["status"] in {"queued", "rendering", "succeeded", "failed"}
                ):
                    return
                raise ProgramRenderConflict("segment is not pending")
            changed = connection.execute(
                text(
                    "UPDATE program_render_segments SET render_job_id=:job,status='queued' "
                    "WHERE program_render_run_id=:run AND segment_index=:index "
                    "AND status='pending' AND render_job_id IS NULL"
                ),
                {"job": str(render_job_id), "run": str(program_run_id),
                 "index": segment_index},
            ).rowcount
            if changed != 1:
                raise ProgramRenderConflict("segment is not pending")
            connection.execute(
                text(
                    "UPDATE program_render_runs SET status='rendering' "
                    "WHERE id=:run AND status='compiling'"
                ),
                {"run": str(program_run_id)},
            )

    def record_segment_artifact(
        self, program_run_id: UUID, segment_index: int, *, artifact_id: UUID,
        artifact_sha256: str,
    ) -> None:
        with self._engine.begin() as connection:
            identity = (
                connection.execute(
                    text(
                        "SELECT segments.status,segments.input_artifact_id,"
                        "segments.input_artifact_sha256,segments.render_job_id,artifacts.sha256 "
                        "FROM program_render_segments segments "
                        "JOIN program_render_runs runs "
                        "ON runs.id=segments.program_render_run_id "
                        "JOIN artifacts ON artifacts.id=:artifact "
                        "AND artifacts.render_job_id=segments.render_job_id "
                        "AND artifacts.project_id=runs.project_id "
                        "AND artifacts.owner_id=runs.owner_id AND artifacts.kind='video' "
                        "WHERE segments.program_render_run_id=:run "
                        "AND segments.segment_index=:index"
                    ),
                    {
                        "artifact": str(artifact_id),
                        "run": str(program_run_id),
                        "index": segment_index,
                    },
                )
                .mappings()
                .one_or_none()
            )
            if identity is None or identity["sha256"] != artifact_sha256:
                raise ProgramRenderConflict("segment artifact identity differs")
            if identity["status"] == "succeeded":
                if (
                    identity["input_artifact_id"] == str(artifact_id)
                    and identity["input_artifact_sha256"] == artifact_sha256
                ):
                    return
                raise ProgramRenderConflict("segment artifact identity differs")
            changed = connection.execute(
                text(
                    "UPDATE program_render_segments SET input_artifact_id=:artifact,"
                    "input_artifact_sha256=:hash,status='succeeded' "
                    "WHERE program_render_run_id=:run AND segment_index=:index "
                    "AND status IN ('queued','rendering')"
                ),
                {"artifact": str(artifact_id), "hash": artifact_sha256,
                 "run": str(program_run_id), "index": segment_index},
            ).rowcount
            if changed != 1:
                raise ProgramRenderConflict("segment cannot accept artifact")

    def record_segment_failure(
        self, program_run_id: UUID, segment_index: int, failure_code: str
    ) -> None:
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT status,failure_code FROM program_render_segments "
                        "WHERE program_render_run_id=:run AND segment_index=:index"
                    ),
                    {"run": str(program_run_id), "index": segment_index},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProgramRenderConflict("program render segment was not found")
            if row["status"] == "failed":
                if row["failure_code"] == failure_code:
                    return
                raise ProgramRenderConflict("segment failure identity differs")
            changed = connection.execute(
                text(
                    "UPDATE program_render_segments SET status='failed',failure_code=:failure "
                    "WHERE program_render_run_id=:run AND segment_index=:index "
                    "AND status IN ('pending','queued','rendering')"
                ),
                {"failure": failure_code, "run": str(program_run_id), "index": segment_index},
            ).rowcount
            if changed != 1:
                raise ProgramRenderConflict("segment cannot accept failure")

    def mark_composing(self, program_run_id: UUID) -> None:
        with self._engine.begin() as connection:
            changed = connection.execute(
                text(
                    "UPDATE program_render_runs SET status='composing' WHERE id=:run "
                    "AND status IN ('compiling','rendering') AND NOT EXISTS ("
                    "SELECT 1 FROM program_render_segments WHERE program_render_run_id=:run "
                    "AND status!='succeeded')"
                ),
                {"run": str(program_run_id)},
            ).rowcount
            status = connection.execute(
                text("SELECT status FROM program_render_runs WHERE id=:run"),
                {"run": str(program_run_id)},
            ).scalar_one_or_none()
        if changed != 1 and status not in {"composing", "succeeded"}:
            raise ProgramRenderConflict("program render is not ready to compose")

    def finish(self, program_run_id: UUID, *, failure_code: str | None = None) -> None:
        terminal = "failed" if failure_code else "succeeded"
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    text("SELECT status,failure_code FROM program_render_runs WHERE id=:run"),
                    {"run": str(program_run_id)},
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProgramRenderConflict("program render run was not found")
            if row["status"] in {"succeeded", "failed"}:
                if row["status"] == terminal and row["failure_code"] == failure_code:
                    return
                raise ProgramRenderConflict("program render terminal identity differs")
            if terminal == "succeeded":
                incomplete = connection.execute(
                    text(
                        "SELECT 1 FROM program_render_segments "
                        "WHERE program_render_run_id=:run AND status!='succeeded' LIMIT 1"
                    ),
                    {"run": str(program_run_id)},
                ).one_or_none()
                if incomplete is not None:
                    raise ProgramRenderConflict("program render has incomplete segments")
            connection.execute(
                text(
                    "UPDATE program_render_runs SET status=:status,failure_code=:failure "
                    "WHERE id=:run AND status NOT IN ('succeeded','failed')"
                ),
                {"status": terminal, "failure": failure_code, "run": str(program_run_id)},
            )

    @staticmethod
    def _run(row: RowMapping) -> ProgramRenderRun:
        return ProgramRenderRun.model_validate(dict(row))

    @staticmethod
    def _segment(row: RowMapping) -> ProgramRenderSegment:
        values = dict(row)
        values.pop("source_code", None)
        return ProgramRenderSegment.model_validate(values)
