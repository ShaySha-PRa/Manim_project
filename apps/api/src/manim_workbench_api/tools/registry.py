"""Registered scientific tools. Never execute free Python from the model."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from manim_workbench_contracts import AssetSource, ToolOp, ToolRun
from manim_workbench_runner.sandbox.compute_runtime import ComputeArtifact, execute_tool
from sqlalchemy import Engine

from manim_workbench_api.assets.scientific import ingest_csv_text, inspect_numpy_file
from manim_workbench_api.assets.versions import persist_asset_version

_CSV_OPS = frozenset({ToolOp.CSV_ANOMALY.value, ToolOp.ODE_COMPARE.value})


def invoke(
    op: ToolOp | str,
    params: Mapping[str, Any],
    *,
    input_text: str | None = None,
    output_root: Path | None = None,
    engine: Engine | None = None,
    owner_id: UUID | None = None,
    project_id: UUID | None = None,
) -> ToolRun:
    name = op.value if isinstance(op, ToolOp) else op
    input_asset = None
    derived_from = None
    if name in _CSV_OPS:
        input_asset = ingest_csv_text(input_text or "")
        derived_from = input_asset.sha256
    artifact: ComputeArtifact = execute_tool(
        name,
        params,
        input_text=input_text,
        output_root=output_root,
    )
    asset_version = inspect_numpy_file(
        artifact.artifact_path,
        source=AssetSource.TOOL_OUTPUT,
        derived_from=derived_from,
    )
    if engine is not None:
        if input_asset is not None:
            persist_asset_version(
                engine,
                input_asset,
                owner_id=owner_id,
                project_id=project_id,
                payload_text=input_text,
            )
        persist_asset_version(
            engine, asset_version, owner_id=owner_id, project_id=project_id
        )
    return ToolRun(
        id=name.replace(".", "_")[:64],
        op=ToolOp(name),
        params_sha256=artifact.params_sha256,
        input_sha256=artifact.input_sha256,
        output_sha256=artifact.output_sha256,
        artifact_ref=artifact.artifact_ref,
        artifact_path=str(artifact.artifact_path),
        assertions=artifact.assertions,
        asset_version=asset_version,
        input_asset_version=input_asset,
    )
