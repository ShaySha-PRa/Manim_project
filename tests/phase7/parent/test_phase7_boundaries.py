from __future__ import annotations

from importlib import import_module

import pytest


@pytest.mark.parametrize(
    ("module_name", "symbol"),
    [
        ("manim_workbench_api.code_generation.prompts", "build_code_generation_messages"),
        ("manim_workbench_api.code_generation.security", "validate_source_security"),
        ("manim_workbench_api.code_generation.validation", "preflight_source"),
        ("manim_workbench_api.code_generation.repair", "RepairOrchestrator"),
        ("benchmarks.phase7.evaluator", "Phase7Evaluator"),
    ],
)
def test_parallel_implementation_boundary_exists(module_name: str, symbol: str) -> None:
    module = import_module(module_name)
    assert getattr(module, symbol)
