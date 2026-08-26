"""Atomically publish owner-scoped workflow video artifacts."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from manim_workbench_contracts import RenderProfile, WorkflowArtifact
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError


class WorkflowArtifactConflict(ValueError):
    pass


class WorkflowArtifactStore:
    def __init__(self, engine: Engine, artifact_root: Path, staging_root: Path) -> None:
        artifact_root.mkdir(parents=True, exist_ok=True)
        staging_root.mkdir(parents=True, exist_ok=True)
        if artifact_root.is_symlink() or staging_root.is_symlink():
            raise ValueError("workflow artifact roots cannot be symlinks")
        self._engine = engine
        self._artifact_root = artifact_root.resolve(strict=True)
        self._staging_root = staging_root.resolve(strict=True)

    @property
    def artifact_root(self) -> Path:
        return self._artifact_root

    def reuse(
        self,
        source_artifact: WorkflowArtifact,
        *,
        scene_block_run_id: UUID | None = None,
        composition_run_id: UUID | None = None,
    ) -> WorkflowArtifact:
        source = self.verified_path(source_artifact)
        staging = self._staging_root / f"cache-reuse-{uuid4().hex}.mp4"
        staging.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as source_file, staging.open("xb") as target_file:
            while chunk := source_file.read(1024 * 1024):
                target_file.write(chunk)
        return self.publish(
            staging,
            project_id=source_artifact.project_id,
            owner_id=source_artifact.owner_id,
            profile=source_artifact.profile,
            duration_seconds=source_artifact.duration_seconds,
            scene_block_run_id=scene_block_run_id,
            composition_run_id=composition_run_id,
        )

    def publish(
        self,
        source: Path,
        *,
        project_id: UUID,
        owner_id: UUID,
        profile: RenderProfile,
        duration_seconds: float,
        scene_block_run_id: UUID | None = None,
        composition_run_id: UUID | None = None,
    ) -> WorkflowArtifact:
        if (scene_block_run_id is None) == (composition_run_id is None):
            raise ValueError("exactly one workflow artifact run source is required")
        if source.is_symlink() or not source.is_file():
            raise ValueError("workflow artifact source must be a regular staging file")
        if not 0 < duration_seconds <= 600:
            raise ValueError("workflow artifact duration is invalid")
        source = source.resolve(strict=True)
        if not source.is_relative_to(self._staging_root):
            raise ValueError("workflow artifact source must stay inside staging")
        payload_hash = sha256(source.read_bytes()).hexdigest()
        byte_size = source.stat().st_size
        if byte_size <= 0:
            raise ValueError("workflow artifact cannot be empty")
        run_id = scene_block_run_id or composition_run_id
        assert run_id is not None
        relative = Path("workflows") / str(owner_id) / str(run_id) / f"{profile.value}.mp4"
        destination = self._safe_destination(relative)
        existing = self.find_for_run(
            project_id=project_id,
            owner_id=owner_id,
            profile=profile,
            scene_block_run_id=scene_block_run_id,
            composition_run_id=composition_run_id,
        )
        if existing is not None:
            self._verify_existing(
                existing, destination, payload_hash, byte_size, duration_seconds
            )
            source.unlink()
            return existing
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_file():
                raise WorkflowArtifactConflict("workflow artifact destination is unsafe")
            if sha256(destination.read_bytes()).hexdigest() != payload_hash:
                raise WorkflowArtifactConflict("published artifact conflicts with staging")
            source.unlink()
        else:
            os.replace(source, destination)
        artifact = WorkflowArtifact(
            id=uuid4(),
            project_id=project_id,
            owner_id=owner_id,
            scene_block_run_id=scene_block_run_id,
            composition_run_id=composition_run_id,
            profile=profile,
            relative_path=relative.as_posix(),
            sha256=payload_hash,
            byte_size=byte_size,
            duration_seconds=duration_seconds,
            created_at=datetime.now(timezone.utc),
        )
        try:
            self._insert(artifact)
        except IntegrityError:
            winner = self.find_for_run(
                project_id=project_id,
                owner_id=owner_id,
                profile=profile,
                scene_block_run_id=scene_block_run_id,
                composition_run_id=composition_run_id,
            )
            if winner is None:
                raise
            self._verify_existing(
                winner, destination, payload_hash, byte_size, duration_seconds
            )
            return winner
        return artifact

    def find_for_run(
        self,
        *,
        project_id: UUID,
        owner_id: UUID,
        profile: RenderProfile,
        scene_block_run_id: UUID | None = None,
        composition_run_id: UUID | None = None,
    ) -> WorkflowArtifact | None:
        column = "scene_block_run_id" if scene_block_run_id else "composition_run_id"
        run_id = scene_block_run_id or composition_run_id
        if run_id is None:
            return None
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    f"SELECT * FROM workflow_artifacts WHERE {column}=:run "
                    "AND project_id=:project AND owner_id=:owner AND profile=:profile"
                ),
                {
                    "run": str(run_id),
                    "project": str(project_id),
                    "owner": str(owner_id),
                    "profile": profile.value,
                },
            ).mappings().one_or_none()
        return WorkflowArtifact.model_validate(dict(row)) if row else None

    def get(
        self,
        artifact_id: UUID,
        *,
        project_id: UUID,
        owner_id: UUID,
    ) -> WorkflowArtifact | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT w.* FROM workflow_artifacts w "
                        "JOIN projects p ON p.id=w.project_id "
                        "WHERE w.id=:id AND w.project_id=:project AND w.owner_id=:owner "
                        "AND p.owner_id=:owner AND p.archived_at IS NULL"
                    ),
                    {
                        "id": str(artifact_id),
                        "project": str(project_id),
                        "owner": str(owner_id),
                    },
                )
                .mappings()
                .one_or_none()
            )
        return WorkflowArtifact.model_validate(dict(row)) if row else None

    def _insert(self, artifact: WorkflowArtifact) -> None:
        with self._engine.begin() as connection:
            table = (
                "scene_block_runs"
                if artifact.scene_block_run_id is not None
                else "workflow_composition_runs"
            )
            run_id = artifact.scene_block_run_id or artifact.composition_run_id
            found = connection.execute(
                text(
                    f"SELECT r.id FROM {table} r JOIN projects p ON p.id=r.project_id "
                    "WHERE r.id=:run AND r.project_id=:project AND r.owner_id=:owner "
                    "AND p.owner_id=:owner AND p.archived_at IS NULL"
                ),
                {
                    "run": str(run_id),
                    "project": str(artifact.project_id),
                    "owner": str(artifact.owner_id),
                },
            ).one_or_none()
            if found is None:
                raise ValueError("workflow artifact run was not found")
            connection.execute(
                text(
                    "INSERT INTO workflow_artifacts "
                    "(id,project_id,owner_id,scene_block_run_id,composition_run_id,profile,"
                    "relative_path,sha256,byte_size,duration_seconds,media_type,created_at) VALUES "
                    "(:id,:project,:owner,:scene,:composition,:profile,:path,:sha,:size,"
                    ":duration,:media,:created)"
                ),
                {
                    "id": str(artifact.id),
                    "project": str(artifact.project_id),
                    "owner": str(artifact.owner_id),
                    "scene": (
                        str(artifact.scene_block_run_id)
                        if artifact.scene_block_run_id
                        else None
                    ),
                    "composition": (
                        str(artifact.composition_run_id)
                        if artifact.composition_run_id
                        else None
                    ),
                    "profile": artifact.profile.value,
                    "path": artifact.relative_path,
                    "sha": artifact.sha256,
                    "size": artifact.byte_size,
                    "duration": artifact.duration_seconds,
                    "media": artifact.media_type,
                    "created": artifact.created_at.isoformat(),
                },
            )

    def _safe_destination(self, relative: Path) -> Path:
        parent = self._artifact_root
        for part in relative.parent.parts:
            parent = parent / part
            if parent.is_symlink():
                raise ValueError("workflow artifact destination contains a symlink")
            parent.mkdir(exist_ok=True)
        destination = parent / relative.name
        if not destination.resolve(strict=False).is_relative_to(self._artifact_root):
            raise ValueError("workflow artifact destination escaped root")
        return destination

    @staticmethod
    def _verify_existing(
        artifact: WorkflowArtifact,
        path: Path,
        expected_hash: str,
        expected_size: int,
        expected_duration: float,
    ) -> None:
        if (
            artifact.sha256 != expected_hash
            or artifact.byte_size != expected_size
            or abs(artifact.duration_seconds - expected_duration) > 1e-6
            or path.is_symlink()
            or not path.is_file()
            or sha256(path.read_bytes()).hexdigest() != expected_hash
        ):
            raise WorkflowArtifactConflict("existing workflow artifact evidence differs")

    def verified_path(self, artifact: WorkflowArtifact) -> Path:
        """Resolve and verify one already published artifact inside the configured root."""

        path = self._artifact_root / artifact.relative_path
        self._verify_existing(
            artifact,
            path,
            artifact.sha256,
            artifact.byte_size,
            artifact.duration_seconds,
        )
        return path.resolve(strict=True)
