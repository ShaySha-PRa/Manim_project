from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from manim_workbench_contracts import (
    GlobalBrief,
    RenderProfile,
    SceneBlockVersion,
    ScenePipeline,
)
from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class SceneCacheVersions:
    pipeline: str
    template: str
    tool: str
    compiler: str
    renderer: str


@dataclass(frozen=True, slots=True)
class CacheArtifactDescriptor:
    owner_id: UUID
    project_id: UUID
    profile: RenderProfile
    relative_path: str
    sha256: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class CacheValidationError(Exception):
    code: str


class MediaProbe(Protocol):
    def __call__(self, path: Path) -> bool: ...


class CacheArtifactLookup(Protocol):
    def find_scene_cache_artifact(
        self,
        cache_key: str,
        project_id: UUID,
        owner_id: UUID,
        profile: RenderProfile,
    ) -> CacheArtifactDescriptor | None: ...


@dataclass(frozen=True, slots=True)
class SceneCacheHit:
    cache_key: str
    descriptor: CacheArtifactDescriptor
    path: Path


class SceneCacheService:
    def __init__(
        self,
        lookup: CacheArtifactLookup,
        *,
        artifact_root: Path,
        media_probe: MediaProbe,
    ) -> None:
        self._lookup = lookup
        self._artifact_root = artifact_root
        self._media_probe = media_probe

    def lookup(
        self,
        cache_key: str,
        *,
        owner_id: UUID,
        project_id: UUID,
        profile: RenderProfile,
    ) -> SceneCacheHit | None:
        descriptor = self._lookup.find_scene_cache_artifact(
            cache_key, project_id, owner_id, profile
        )
        if descriptor is None:
            return None
        try:
            path = verify_cache_artifact(
                descriptor,
                artifact_root=self._artifact_root,
                owner_id=owner_id,
                project_id=project_id,
                profile=profile,
                media_probe=self._media_probe,
            )
        except CacheValidationError:
            return None
        return SceneCacheHit(cache_key=cache_key, descriptor=descriptor, path=path)

    def lookup_many(
        self,
        cache_keys: tuple[str, ...],
        *,
        owner_id: UUID,
        project_id: UUID,
        profile: RenderProfile,
    ) -> tuple[SceneCacheHit | None, ...]:
        return tuple(
            self.lookup(
                key,
                owner_id=owner_id,
                project_id=project_id,
                profile=profile,
            )
            for key in cache_keys
        )


def scene_cache_key(
    *,
    block: SceneBlockVersion,
    global_brief: GlobalBrief,
    asset_hashes: tuple[str, ...],
    pipeline: ScenePipeline,
    versions: SceneCacheVersions,
    profile: RenderProfile,
    previous_scene_summary: str | None = None,
) -> str:
    payload = {
        "schema": "scene-cache-v1",
        "scene": {
            "title": block.title,
            "prompt": block.prompt,
            "pipeline_mode": block.pipeline_mode,
            "target_duration_seconds": block.target_duration_seconds,
        },
        "global_brief": global_brief,
        "asset_hashes": asset_hashes,
        "pipeline": pipeline,
        "versions": asdict(versions),
        "profile": profile,
        "previous_scene_summary": previous_scene_summary,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def verify_cache_artifact(
    descriptor: CacheArtifactDescriptor,
    *,
    artifact_root: Path,
    owner_id: UUID,
    project_id: UUID,
    profile: RenderProfile,
    media_probe: MediaProbe,
) -> Path:
    if (
        descriptor.owner_id != owner_id
        or descriptor.project_id != project_id
        or descriptor.profile is not profile
    ):
        raise CacheValidationError("cache_artifact_boundary_mismatch")
    root = artifact_root.resolve()
    path = (root / descriptor.relative_path).resolve()
    if path == root or root not in path.parents or not path.is_file():
        raise CacheValidationError("cache_artifact_path_invalid")
    if descriptor.byte_size <= 0 or path.stat().st_size != descriptor.byte_size:
        raise CacheValidationError("cache_artifact_size_mismatch")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != descriptor.sha256:
        raise CacheValidationError("cache_artifact_hash_mismatch")
    if not media_probe(path):
        raise CacheValidationError("cache_artifact_media_invalid")
    return path


def _canonicalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonicalize(value.model_dump(mode="json"))
    if isinstance(value, Enum):
        return _canonicalize(value.value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    if isinstance(value, dict):
        return {str(key): _canonicalize(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_canonicalize(item) for item in value]
    if value is None or isinstance(value, bool | int | float):
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")
