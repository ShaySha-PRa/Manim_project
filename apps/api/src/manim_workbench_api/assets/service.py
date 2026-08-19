"""Owner-scoped user image assets. Files never become executable Python."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from manim_workbench_contracts.ir import (
    GeometryConstruction,
    IrObjectType,
    SceneObject,
    UserAsset,
    UserAssetKind,
)
from sqlalchemy import Engine, text

from manim_workbench_api.projects.errors import PROJECT_NOT_FOUND

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,200}$")
_ALLOWED_TYPES = {"image/png": ".png", "image/jpeg": ".jpg"}
_MAX_BYTES = 8_000_000


class AssetError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def extract_constructions(payload: bytes, content_type: str) -> tuple[SceneObject, ...]:
    """Turn an uploaded file into IR objects. JSON sidecars are trusted only as constructions."""
    if content_type == "application/json":
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AssetError("invalid_construction_json", "construction JSON is invalid") from error
        items = document.get("constructions") if isinstance(document, dict) else None
        if not isinstance(items, list) or not items:
            raise AssetError("invalid_construction_json", "construction JSON has no constructions")
        objects: list[SceneObject] = []
        for index, item in enumerate(items[:24]):
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "circle"))
            try:
                object_type = IrObjectType(kind)
            except ValueError:
                object_type = IrObjectType.CIRCLE
            vertices = item.get("vertices") or ()
            if object_type is IrObjectType.POLYGON and len(tuple(vertices)) < 3:
                object_type = IrObjectType.CIRCLE
            objects.append(
                SceneObject(
                    id=f"extracted_{index}",
                    type=object_type,
                    radius=float(item["radius"]) if "radius" in item else 1.0,
                    x=float(item.get("x", 0)),
                    y=float(item.get("y", 0)),
                    vertices=tuple((float(pair[0]), float(pair[1])) for pair in vertices)
                    if object_type is IrObjectType.POLYGON
                    else (),
                    text=str(item["label"]) if item.get("label") else None,
                )
            )
        if not objects:
            raise AssetError("invalid_construction_json", "construction JSON produced no objects")
        return tuple(objects)
    if content_type not in _ALLOWED_TYPES:
        raise AssetError(
            "unsupported_asset_type",
            "only png, jpeg, or construction JSON is allowed",
        )
    digest = hashlib.sha256(payload).hexdigest()
    return (
        SceneObject(
            id="source_image",
            type=IrObjectType.IMAGE_REF,
            asset_sha256=digest,
        ),
    )


class AssetRepository:
    def __init__(self, engine: Engine, root: Path) -> None:
        self._engine = engine
        self._root = root

    def save(
        self,
        *,
        project_id: UUID,
        owner_id: UUID,
        filename: str,
        content_type: str,
        payload: bytes,
    ) -> UserAsset:
        if not _SAFE_NAME.fullmatch(filename):
            raise AssetError("invalid_filename", "filename is not allowed")
        if content_type not in {*_ALLOWED_TYPES, "application/json"}:
            raise AssetError("unsupported_asset_type", "content type is not allowed")
        if not 1 <= len(payload) <= _MAX_BYTES:
            raise AssetError("asset_too_large", "asset exceeds the size limit")
        self._assert_owner(project_id, owner_id)
        digest = hashlib.sha256(payload).hexdigest()
        extension = _ALLOWED_TYPES.get(content_type, ".json")
        stored = self._root / str(owner_id) / str(project_id) / f"{digest}{extension}"
        stored.parent.mkdir(parents=True, exist_ok=True)
        stored.write_bytes(payload)
        asset = UserAsset(
            id=uuid4(),
            project_id=project_id,
            owner_id=owner_id,
            kind=(
                UserAssetKind.IMAGE
                if content_type.startswith("image/")
                else UserAssetKind.CONSTRUCTION_JSON
            ),
            sha256=digest,
            byte_size=len(payload),
            content_type=content_type,
            original_filename=filename,
        )
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO user_assets (
                        id, project_id, owner_id, kind, sha256, byte_size, content_type,
                        original_filename, relative_path, created_at
                    ) VALUES (
                        :id, :project_id, :owner_id, :kind, :sha256, :byte_size, :content_type,
                        :original_filename, :relative_path, :created_at
                    )
                    """
                ),
                {
                    **asset.model_dump(mode="json"),
                    "relative_path": str(stored.relative_to(self._root)),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        return asset

    def _assert_owner(self, project_id: UUID, owner_id: UUID) -> None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT id FROM projects WHERE id = :project_id AND owner_id = :owner_id"
                ),
                {"project_id": str(project_id), "owner_id": str(owner_id)},
            ).one_or_none()
        if row is None:
            raise PROJECT_NOT_FOUND


def constructions_to_ir(objects: tuple[SceneObject, ...]) -> tuple[GeometryConstruction, ...]:
    return tuple(
        GeometryConstruction(object_id=item.id, kind=item.type, label=item.text)
        for item in objects
        if item.type is not IrObjectType.IMAGE_REF
    )
