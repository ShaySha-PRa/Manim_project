from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

SNAPSHOT_FIELDS = (
    "model_spec",
    "parameters",
    "observables",
    "assumptions",
    "visualization",
    "code_files",
)


def json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [json_value(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def json_loads(value: object) -> Any:
    return json.loads(str(value))


def editable_snapshot(model: BaseModel) -> dict[str, Any]:
    dumped = model.model_dump(mode="json")
    return {field: dumped[field] for field in SNAPSHOT_FIELDS}


def snapshot_columns(snapshot: Mapping[str, Any]) -> dict[str, str]:
    return {f"{field}_json": canonical_json(snapshot[field]) for field in SNAPSHOT_FIELDS}


def snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(snapshot)).encode("utf-8")).hexdigest()
