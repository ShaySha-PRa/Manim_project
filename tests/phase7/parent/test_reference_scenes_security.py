from __future__ import annotations

from manim_workbench_api.code_generation.prompts.builder import _reference_examples
from manim_workbench_api.code_generation.security import validate_source_security
from manim_workbench_contracts import CodeGenerationCategory


def test_all_injected_reference_scenes_pass_the_production_ast_gate() -> None:
    examples = tuple(
        example
        for category in CodeGenerationCategory
        for example in _reference_examples(category)
    )

    assert len(examples) == 12
    for example in examples:
        report = validate_source_security(example["source"])
        assert report.allowed, (example["scene_id"], report.findings)
