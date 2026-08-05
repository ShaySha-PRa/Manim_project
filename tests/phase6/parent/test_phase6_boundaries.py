from __future__ import annotations

from importlib import import_module

import pytest


@pytest.mark.parametrize(
    ("module_name", "symbol"),
    [
        ("manim_workbench_api.content_plans.provider", "DeepSeekProvider"),
        ("manim_workbench_api.content_plans.validation", "validate_content_plan_response"),
        ("manim_workbench_api.content_plans.prompts", "build_content_plan_messages"),
        ("benchmarks.phase6.evaluator", "Phase6Evaluator"),
    ],
)
def test_parallel_implementation_boundary_exists(module_name: str, symbol: str) -> None:
    module = import_module(module_name)
    assert getattr(module, symbol)
