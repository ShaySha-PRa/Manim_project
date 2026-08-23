import pytest
from manim_workbench_api.code_generation.gallery_fixtures import (
    following_graph_camera_storyboard,
    mixed_formula_geometry_threed_storyboard,
)
from manim_workbench_api.code_generation.ir_compiler import (
    IrCompileError,
    compile_storyboard,
    scene_base_for_step,
    synthesize_storyboard,
)
from manim_workbench_api.code_generation.security import validate_source_security
from manim_workbench_api.code_generation.validation import preflight_source
from manim_workbench_api.quality.temporal import analyze_temporal_quality
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


def test_formula_synthesis_preserves_every_step_and_allocates_the_target_timeline() -> None:
    expressions = ("x²-2x-1=0", "(x-1)²=2", "x=1±√2")
    storyboard = synthesize_storyboard(
        title="配方法求根",
        target_duration_seconds=60,
        category="formula_derivation",
        expressions=expressions,
        explanations=("移项", "配方", "开平方"),
    )
    source = compile_storyboard(storyboard).segments[0].source
    report = analyze_temporal_quality(source, target_duration_seconds=60)

    assert all(expression in source for expression in expressions)
    assert all(explanation in source for explanation in ("移项", "配方", "开平方"))
    assert "Indicate(" in source
    assert "equation = equation_next" not in source
    assert "reason = reason_next" not in source
    assert report.estimated_duration_seconds == 60
    assert max(event.duration_seconds or 0 for event in report.events) <= 4
    assert not {item.code.value for item in report.diagnostics} & {
        "duration_too_short",
        "duration_too_long",
        "terminal_wait_padding",
    }


def test_formula_synthesis_fits_long_technical_explanations_inside_the_frame() -> None:
    storyboard = synthesize_storyboard(
        title="圆面积公式的直观推导",
        target_duration_seconds=30,
        category="formula_derivation",
        expressions=("C = 2πr", "A = (1/2) * C * r = (1/2) * 2πr * r = πr²"),
        explanations=(
            "圆的周长公式，其中 r 为半径，π 为圆周率。",
            "将圆切分为若干扇形，重排成近似矩形，其宽为半周长 πr，高为半径 r，故面积 A = πr²。",
        ),
    )

    source = compile_storyboard(storyboard).segments[0].source

    assert "font_size=24, color=BLUE" in source
    assert "font_size=21, color=BLUE" in source
    assert "Indicate(reason, scale_factor=1.05)" in source
    assert validate_source_security(source).allowed
    assert preflight_source(source).ok


def test_function_synthesis_compiles_shifted_parabola_and_critical_features() -> None:
    expressions = ("y=x²", "y=(x-1)²-2", "x=1±√2")
    storyboard = synthesize_storyboard(
        title="抛物线顶点式",
        target_duration_seconds=60,
        category="function_visualization",
        expressions=expressions,
        explanations=("基础图像", "向右平移1再向下平移2", "求两个零点"),
    )
    source = compile_storyboard(storyboard).segments[0].source
    report = analyze_temporal_quality(source, target_duration_seconds=60)

    assert all(expression in source for expression in expressions)
    assert "return (x ** 2)" in source
    assert "return (((x - 1) ** 2) - 2)" in source
    assert "vertex" in source
    assert "symmetry_axis" in source
    assert "root_0" in source and "root_1" in source
    assert "return x ** 3" not in source
    assert "lambda" not in source
    assert validate_source_security(source).allowed
    assert preflight_source(source).ok
    assert report.estimated_duration_seconds == 60


def test_function_synthesis_rejects_unknown_or_executable_expressions() -> None:
    with pytest.raises(IrCompileError, match="unsupported function expression"):
        synthesize_storyboard(
            title="不安全表达式",
            target_duration_seconds=60,
            category="function_visualization",
            expressions=("y=__import__('os').system('id')",),
            explanations=("不得执行",),
        )


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
