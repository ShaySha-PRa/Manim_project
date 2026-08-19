from manim_workbench_api.code_generation.gallery_fixtures import (
    following_graph_camera_storyboard,
    mixed_formula_geometry_threed_storyboard,
)
from manim_workbench_api.code_generation.ir_compiler import (
    compile_storyboard,
    scene_base_for_step,
    synthesize_storyboard,
)
from manim_workbench_api.code_generation.security import validate_source_security
from manim_workbench_api.code_generation.validation import preflight_source
from manim_workbench_contracts.ir import VisualKind


def test_function_synthesis_uses_value_tracker_and_named_redraw() -> None:
    storyboard = synthesize_storyboard(
        title="cubic tangent",
        target_duration_seconds=90,
        category="function_visualization",
        expressions=("y=x^3",),
        explanations=("moving tangent",),
    )
    source = compile_storyboard(storyboard).segments[0].source
    assert "ValueTracker" in source
    assert "always_redraw" in source
    assert "def redraw_" in source
    assert "lambda" not in source
    assert validate_source_security(source).allowed
    assert preflight_source(source).ok


def test_formula_synthesis_uses_transform_matching_tex() -> None:
    storyboard = synthesize_storyboard(
        title="complete the square",
        target_duration_seconds=60,
        category="formula_derivation",
        expressions=("x^2+2x", "(x+1)^2-1"),
        explanations=("add and subtract 1",),
    )
    source = compile_storyboard(storyboard).segments[0].source
    assert "TransformMatchingTex" in source
    assert validate_source_security(source).allowed


def test_zoom_compiles_to_moving_camera_scene() -> None:
    step = following_graph_camera_storyboard().steps[0]
    assert scene_base_for_step(step) == "MovingCameraScene"
    source = compile_storyboard(following_graph_camera_storyboard()).segments[0].source
    assert "class GeneratedScene(MovingCameraScene)" in source
    assert "Restore(self.camera.frame)" in source
    assert validate_source_security(source).allowed
    assert preflight_source(source).ok


def test_mixed_storyboard_splits_threed_from_2d() -> None:
    program = compile_storyboard(mixed_formula_geometry_threed_storyboard())
    assert program.requires_concat
    bases = {segment.scene_base for segment in program.segments}
    assert "ThreeDScene" in bases
    assert "Scene" in bases or "MovingCameraScene" in bases
    three_d = next(segment for segment in program.segments if segment.scene_base == "ThreeDScene")
    assert VisualKind.THREE_D in three_d.visual_kinds
    for segment in program.segments:
        assert validate_source_security(segment.source).allowed
        assert preflight_source(segment.source).ok
