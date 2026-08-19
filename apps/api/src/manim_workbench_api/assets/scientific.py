"""Immutable scientific AssetVersion ingest. Teaching UserAsset is separate."""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

import numpy as np
import pandas as pd
from manim_workbench_contracts import (
    AssetDType,
    AssetField,
    AssetMime,
    AssetSource,
    AssetVersion,
)

MAX_CSV_BYTES = 200_000
MAX_CSV_ROWS = 5_000
MAX_CSV_COLS = 24
MAX_NUMPY_BYTES = 64_000_000
MAX_ARRAYS = 24
MAX_NDIM = 8
METADATA_ARRAYS = frozenset({"assertion_json"})
_COLUMN_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_DTYPE_MAP = {
    np.dtype(np.float32): AssetDType.FLOAT32,
    np.dtype(np.float64): AssetDType.FLOAT64,
    np.dtype(np.int32): AssetDType.INT32,
    np.dtype(np.int64): AssetDType.INT64,
    np.dtype(np.uint8): AssetDType.UINT8,
    np.dtype(np.bool_): AssetDType.BOOL,
}


class AssetIngestError(ValueError):
    """CSV/NPY/NPZ failed closed: size, dtype, pickle, or schema."""


def ingest_csv_text(text: str) -> AssetVersion:
    raw = text.encode("utf-8")
    if not raw.strip():
        raise AssetIngestError("csv is empty")
    if len(raw) > MAX_CSV_BYTES:
        raise AssetIngestError("csv exceeds size limit")
    frame = pd.read_csv(io.StringIO(text))
    if frame.empty:
        raise AssetIngestError("csv has no rows")
    if len(frame.columns) > MAX_CSV_COLS:
        raise AssetIngestError("csv exceeds column limit")
    if len(frame) > MAX_CSV_ROWS:
        raise AssetIngestError("csv exceeds row limit")
    fields: list[AssetField] = []
    for raw_name in frame.columns:
        name = str(raw_name).strip()
        if not _COLUMN_NAME.fullmatch(name):
            raise AssetIngestError(f"invalid column name: {raw_name}")
        array = _numeric_series(frame[raw_name], name)
        fields.append(
            AssetField(name=name, dtype=_map_dtype(array.dtype), shape=(int(array.shape[0]),))
        )
    return AssetVersion(
        sha256=hashlib.sha256(raw).hexdigest(),
        mime=AssetMime.CSV,
        size_bytes=len(raw),
        source=AssetSource.UPLOAD,
        columns=tuple(field.name for field in fields),
        fields=tuple(fields),
    )


def ingest_document(payload: bytes, *, mime: AssetMime) -> AssetVersion:
    if mime not in {AssetMime.TEXT, AssetMime.PDF}:
        raise AssetIngestError("unsupported document mime")
    if not payload:
        raise AssetIngestError("document is empty")
    if len(payload) > MAX_CSV_BYTES:
        raise AssetIngestError("document exceeds size limit")
    return AssetVersion(
        sha256=hashlib.sha256(payload).hexdigest(),
        mime=mime,
        size_bytes=len(payload),
        source=AssetSource.UPLOAD,
        columns=("payload",),
        fields=(AssetField(name="payload", dtype=AssetDType.UINT8, shape=(len(payload),)),),
    )


def inspect_numpy_file(
    path: Path,
    *,
    source: AssetSource,
    derived_from: str | None = None,
) -> AssetVersion:
    suffix = path.suffix.lower()
    if suffix not in {".npy", ".npz"}:
        raise AssetIngestError("expected .npy or .npz")
    raw = path.read_bytes()
    if not raw:
        raise AssetIngestError("numpy file is empty")
    if len(raw) > MAX_NUMPY_BYTES:
        raise AssetIngestError("numpy file exceeds size limit")
    try:
        loaded = np.load(io.BytesIO(raw), allow_pickle=False)
        if suffix == ".npz":
            mime = AssetMime.NPZ
            arrays = {name: loaded[name] for name in loaded.files}
        else:
            mime = AssetMime.NPY
            arrays = {"array": loaded}
    except (ValueError, OSError) as error:
        raise AssetIngestError("numpy pickle or object arrays are forbidden") from error
    fields = _fields_from_arrays(arrays)
    return AssetVersion(
        sha256=hashlib.sha256(raw).hexdigest(),
        mime=mime,
        size_bytes=len(raw),
        source=source,
        columns=tuple(field.name for field in fields),
        fields=tuple(fields),
        derived_from=derived_from,
    )


def _fields_from_arrays(arrays: dict[str, np.ndarray]) -> tuple[AssetField, ...]:
    fields: list[AssetField] = []
    for name, array in arrays.items():
        if name in METADATA_ARRAYS:
            continue
        if not _COLUMN_NAME.fullmatch(name):
            raise AssetIngestError(f"invalid array name: {name}")
        if getattr(array, "dtype", None) is not None and array.dtype.kind == "O":
            raise AssetIngestError("object dtype is forbidden")
        if getattr(array, "ndim", 0) > MAX_NDIM:
            raise AssetIngestError(f"array {name} exceeds dimension limit")
        fields.append(
            AssetField(
                name=name,
                dtype=_map_dtype(np.dtype(array.dtype)),
                shape=tuple(int(dim) for dim in array.shape),
            )
        )
    if not fields:
        raise AssetIngestError("numpy file has no numeric arrays")
    if len(fields) > MAX_ARRAYS:
        raise AssetIngestError("numpy file exceeds array limit")
    return tuple(fields)


def _numeric_series(series: pd.Series, name: str) -> np.ndarray:
    if series.dtype == object or str(series.dtype).startswith("object"):
        raise AssetIngestError(f"column {name} is not numeric")
    array = series.to_numpy()
    if array.dtype.kind not in "biuf":
        raise AssetIngestError(f"column {name} is not numeric")
    return array


def _map_dtype(dtype: np.dtype) -> AssetDType:
    mapped = _DTYPE_MAP.get(np.dtype(dtype))
    if mapped is None:
        raise AssetIngestError(f"unsupported dtype {dtype}")
    return mapped
