from manim_workbench_api.code_generation.gallery_fixtures import (
    GALLERY_SOURCE,
    GALLERY_STORYBOARDS,
    SKIPPED_OFFICIAL_EXAMPLES,
    mixed_formula_geometry_threed_storyboard,
    pythagorean_proof_storyboard,
)
from manim_workbench_api.code_generation.ir_compiler import compile_storyboard
from manim_workbench_api.code_generation.security import validate_source_security
from manim_workbench_api.code_generation.validation import preflight_source


def test_gallery_storyboards_compile_without_lambda() -> None:
    assert GALLERY_SOURCE.startswith("https://docs.manim.community/")
    for name, factory in GALLERY_STORYBOARDS.items():
        program = compile_storyboard(factory())
        assert program.segments, name
        for segment in program.segments:
            source = segment.source
            assert "lambda" not in source, name
            report = validate_source_security(source)
            assert report.allowed, (name, report.findings)
            assert preflight_source(source).ok, name


def test_skipped_official_examples_are_documented() -> None:
    assert set(GALLERY_STORYBOARDS).isdisjoint(SKIPPED_OFFICIAL_EXAMPLES)
    assert "ZoomedScene" in SKIPPED_OFFICIAL_EXAMPLES["MovingZoomedSceneAround"]
    assert "lambda" in SKIPPED_OFFICIAL_EXAMPLES["RotationUpdater"] or "add_updater" in (
        SKIPPED_OFFICIAL_EXAMPLES["RotationUpdater"]
    )


def test_mixed_and_proof_gallery_intents_also_compile() -> None:
    for factory in (mixed_formula_geometry_threed_storyboard, pythagorean_proof_storyboard):
        program = compile_storyboard(factory())
        for segment in program.segments:
            assert validate_source_security(segment.source).allowed
            assert preflight_source(segment.source).ok
