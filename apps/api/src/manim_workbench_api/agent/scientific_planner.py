"""Turn IntentSpec into concrete allowlisted tool calls."""

from __future__ import annotations

from manim_workbench_contracts import IntentSpec, ToolNeed, ToolOp
from manim_workbench_contracts.intent import IntentDomain

_DEFAULTS: dict[ToolOp, dict[str, float | int | str | bool]] = {
    ToolOp.WAVE2D_SUPERPOSITION: {"c": 1.15, "k": 6.2, "nx": 64, "ny": 64, "nt": 36},
    ToolOp.FOURIER_SQUARE_WAVE: {"n_max": 31, "samples": 240},
    ToolOp.LORENZ_ENSEMBLE: {"delta": 1e-5, "samples": 160, "t_end": 30.0},
    ToolOp.PID_STEP_RESPONSE: {"samples": 160, "t_end": 8.0},
    ToolOp.CSV_ANOMALY: {"center": 350.0, "width": 20.0},
    ToolOp.FRENET_FRAME: {"samples": 80},
}

_DOMAIN_OPS = {
    IntentDomain.PHYSICS_WAVE: ToolOp.WAVE2D_SUPERPOSITION,
    IntentDomain.MATH_SIGNAL: ToolOp.FOURIER_SQUARE_WAVE,
    IntentDomain.DYNAMICAL_SYSTEMS: ToolOp.LORENZ_ENSEMBLE,
    IntentDomain.CONTROL: ToolOp.PID_STEP_RESPONSE,
    IntentDomain.DATA_ANALYSIS: ToolOp.CSV_ANOMALY,
    IntentDomain.GEOMETRY_DIFF3D: ToolOp.FRENET_FRAME,
}


def plan_tools(intent: IntentSpec) -> tuple[ToolNeed, ...]:
    if intent.tools_needed:
        planned: list[ToolNeed] = []
        for need in intent.tools_needed:
            merged = {**_DEFAULTS.get(need.op, {}), **need.params}
            planned.append(ToolNeed(op=need.op, params=merged))
        return tuple(planned)
    op = _DOMAIN_OPS.get(intent.domain)
    if op is None:
        return ()
    return (ToolNeed(op=op, params=dict(_DEFAULTS[op])),)
