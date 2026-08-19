"""Append-only AssetVersion rows. Teaching UserAsset is a separate table."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from manim_workbench_contracts import AssetVersion
from sqlalchemy import Engine, text


def persist_asset_version(
    engine: Engine,
    asset: AssetVersion,
    *,
    owner_id: UUID | None = None,
    project_id: UUID | None = None,
) -> None:
    payload = {
        "id": str(uuid4()),
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
