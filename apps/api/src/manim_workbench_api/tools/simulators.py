"""Allowlisted simulator plugins. New ops cannot come from the model."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from manim_workbench_api.tools.kernels import (
    ALLOWED_OPS,
    KernelResult,
    allowed_ops,
    register_simulator,
    unregister_simulator,
)

SimulatorFn = Callable[[Mapping[str, object], str | None], KernelResult]

__all__ = [
    "ALLOWED_OPS",
    "KernelResult",
    "SimulatorFn",
    "allowed_ops",
    "register_simulator",
    "unregister_simulator",
]
