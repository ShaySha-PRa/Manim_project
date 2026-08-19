"""Registered scientific tools. Never execute free Python from the model."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from manim_workbench_contracts import ToolOp, ToolRun
from manim_workbench_runner.sandbox.compute_runtime import ComputeArtifact, execute_tool


def invoke(
    op: ToolOp | str,
    params: Mapping[str, Any],
    *,
    input_text: str | None = None,
    output_root: Path | None = None,
) -> ToolRun:
    name = op.value if isinstance(op, ToolOp) else op
    artifact: ComputeArtifact = execute_tool(
        name,
        params,
        input_text=input_text,
        output_root=output_root,
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
    )
