"""Validate AnimationIR 2.0 before deterministic compilation."""

from __future__ import annotations

from manim_workbench_contracts import ToolRun
from manim_workbench_contracts.animation_ir import AnimationIR, ObjectType


class IrValidationError(ValueError):
    """IR cannot be compiled."""


def validate_animation_ir(ir: AnimationIR, tool_runs: tuple[ToolRun, ...]) -> None:
    if ir.schema_version != "2.0":
        raise IrValidationError("AnimationIR schema_version must be 2.0")
    refs = {run.artifact_ref: run for run in tool_runs}
    if not ir.timeline:
        raise IrValidationError("timeline is required")
    if not ir.assertions:
        raise IrValidationError("scientific assertions are required")
    for data in ir.data:
        run = refs.get(data.artifact_ref)
        if run is None:
            raise IrValidationError(f"missing ToolRun for {data.artifact_ref}")
        if data.output_sha256 != run.output_sha256:
            raise IrValidationError("data output hash does not match ToolRun")
    for obj in ir.objects:
        if obj.type is ObjectType.SCALAR_FIELD and obj.data_ref is None:
            raise IrValidationError("scalar_field requires data_ref")
    dumped = ir.model_dump_json()
    if "lambda" in dumped or "np.exp" in dumped:
        raise IrValidationError("IR must not embed free Python kernels")
