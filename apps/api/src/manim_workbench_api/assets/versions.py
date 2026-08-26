"""Append-only AssetVersion rows. Teaching UserAsset is a separate table."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from manim_workbench_contracts import AssetVersion
from sqlalchemy import Engine, text


def persist_asset_version(
    engine: Engine,
    asset: AssetVersion,
    *,
    owner_id: UUID | None = None,
    project_id: UUID | None = None,
) -> UUID:
    if (owner_id is None) != (project_id is None):
        raise ValueError("asset scope requires both owner_id and project_id")
    asset_id = uuid4()
    payload = {
        "id": str(asset_id),
        "sha256": asset.sha256,
        "mime": asset.mime.value,
        "size_bytes": asset.size_bytes,
        "source": asset.source.value,
        "derived_from": asset.derived_from,
        "columns_json": json.dumps(list(asset.columns), ensure_ascii=False),
        "fields_json": json.dumps(
            [item.model_dump(mode="json") for item in asset.fields],
            ensure_ascii=False,
        ),
        "owner_id": str(owner_id) if owner_id else None,
        "project_id": str(project_id) if project_id else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO asset_versions (
                    id, sha256, mime, size_bytes, source, derived_from,
                    columns_json, fields_json, owner_id, project_id, created_at
                ) VALUES (
                    :id, :sha256, :mime, :size_bytes, :source, :derived_from,
                    :columns_json, :fields_json, :owner_id, :project_id, :created_at
                )
                ON CONFLICT(sha256) DO NOTHING
                """
            ),
            payload,
        )
        row = connection.execute(
            text("SELECT id FROM asset_versions WHERE sha256=:sha256"),
            {"sha256": asset.sha256},
        ).one()
        asset_id = UUID(str(row.id))
        if owner_id is not None and project_id is not None:
            connection.execute(
                text(
                    "INSERT INTO asset_version_scopes "
                    "(asset_version_id,project_id,owner_id,created_at) "
                    "VALUES (:asset_id,:project_id,:owner_id,:created_at) "
                    "ON CONFLICT(asset_version_id,project_id,owner_id) DO NOTHING"
                ),
                {
                    "asset_id": str(asset_id),
                    "project_id": str(project_id),
                    "owner_id": str(owner_id),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
    return asset_id


def persist_workflow_asset_version(
    engine: Engine,
    asset: AssetVersion,
    *,
    owner_id: UUID,
    project_id: UUID,
    payload_text: str,
) -> UUID:
    """Persist an immutable payload under an owner-and-project scoped identity."""
    raw = payload_text.encode("utf-8")
    if sha256(raw).hexdigest() != asset.sha256 or len(raw) != asset.size_bytes:
        raise ValueError("asset payload does not match immutable metadata")
    asset_id = uuid4()
    values = {
        "id": str(asset_id),
        "project_id": str(project_id),
        "owner_id": str(owner_id),
        "mime": asset.mime.value,
        "source": asset.source.value,
        "columns_json": json.dumps(list(asset.columns), ensure_ascii=False),
        "fields_json": json.dumps(
            [item.model_dump(mode="json") for item in asset.fields], ensure_ascii=False
        ),
        "payload_text": payload_text,
        "sha256": asset.sha256,
        "byte_size": asset.size_bytes,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO workflow_asset_versions "
                "(id,project_id,owner_id,mime,source,columns_json,fields_json,payload_text,"
                "sha256,byte_size,created_at) VALUES "
                "(:id,:project_id,:owner_id,:mime,:source,:columns_json,:fields_json,"
                ":payload_text,:sha256,:byte_size,:created_at) "
                "ON CONFLICT(owner_id,project_id,sha256) DO NOTHING"
            ),
            values,
        )
        stored_id = connection.execute(
            text(
                "SELECT id FROM workflow_asset_versions WHERE owner_id=:owner_id "
                "AND project_id=:project_id AND sha256=:sha256"
            ),
            values,
        ).scalar_one()
    return UUID(str(stored_id))


@dataclass(frozen=True, slots=True)
class StoredAssetPayload:
    asset_version_id: UUID
    mime: str
    text: str
    sha256: str


def load_asset_payloads(
    engine: Engine,
    asset_version_ids: tuple[UUID, ...],
    *,
    owner_id: UUID,
    project_id: UUID,
) -> tuple[StoredAssetPayload, ...]:
    loaded: list[StoredAssetPayload] = []
    with engine.connect() as connection:
        for asset_id in asset_version_ids:
            row = connection.execute(
                text(
                    "SELECT id AS asset_version_id,mime,payload_text,sha256,byte_size "
                    "FROM workflow_asset_versions WHERE id=:asset_id "
                    "AND project_id=:project_id AND owner_id=:owner_id"
                ),
                {
                    "asset_id": str(asset_id),
                    "project_id": str(project_id),
                    "owner_id": str(owner_id),
                },
            ).one_or_none()
            if row is None:
                continue
            raw = row.payload_text.encode("utf-8")
            digest = sha256(raw).hexdigest()
            if (
                digest != row.sha256
                or len(raw) != row.byte_size
            ):
                raise ValueError("stored asset payload integrity check failed")
            loaded.append(
                StoredAssetPayload(
                    asset_version_id=UUID(str(row.asset_version_id)),
                    mime=str(row.mime),
                    text=str(row.payload_text),
                    sha256=digest,
                )
            )
    return tuple(loaded)


def load_asset_version(engine: Engine, sha256: str) -> AssetVersion | None:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT sha256, mime, size_bytes, source, derived_from, columns_json, fields_json
                FROM asset_versions WHERE sha256 = :sha256
                """
            ),
            {"sha256": sha256},
        ).one_or_none()
    if row is None:
        return None
    fields = json.loads(row.fields_json)
    columns = tuple(json.loads(row.columns_json))
    return AssetVersion.model_validate(
        {
            "sha256": row.sha256,
            "mime": row.mime,
            "size_bytes": row.size_bytes,
            "source": row.source,
            "derived_from": row.derived_from,
            "columns": columns,
            "fields": fields,
        }
    )
