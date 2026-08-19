from pathlib import Path

from manim_workbench_api.agent.orchestrator import run_agent
from manim_workbench_api.code_generation.security import validate_source_security
from manim_workbench_api.compiler.manim import compile_animation_ir, renderer_registry
from manim_workbench_contracts.animation_ir import CameraOpKind, VisualPattern
from manim_workbench_contracts.intent import AgentRunOutcome

_COMPILER = (
    Path(__file__).resolve().parents[2]
    / "apps/api/src/manim_workbench_api/compiler/manim.py"
)


def test_compiler_source_is_an_ir_walker() -> None:
    source = _COMPILER.read_text(encoding="utf-8")
    assert "if ir.pattern" not in source
    assert "for dataset in ir.data" in source
    assert "for state in ir.states" in source
    assert "for obj in ir.objects" in source
    assert "for binding in ir.bindings" in source


def test_scene_base_comes_from_camera_and_dimension(tmp_path: Path) -> None:
    result = run_agent("展示傅里叶级数逐渐逼近方波并放大 Gibbs 现象", output_root=tmp_path)
    assert result.outcome is AgentRunOutcome.READY
    assert result.animation_ir is not None
    assert any(op.op is CameraOpKind.ZOOM for op in result.animation_ir.camera)
    backend = renderer_registry.require("manim")
    mutated = result.animation_ir.model_copy(update={"pattern": VisualPattern.FIELD_EVOLUTION})
    assert backend.select_scene_base(mutated) == "MovingCameraScene"
    source = compile_animation_ir(mutated, result.tool_runs).segments[0].source
    assert "class GeneratedScene(MovingCameraScene)" in source
    assert "Axes" in source
    assert "ImageMobject" not in source
    assert "lambda" not in source
    assert validate_source_security(source).allowed


def test_scalar_field_lowers_from_object_type_not_pattern(tmp_path: Path) -> None:
    result = run_agent("展示二维波动方程中两个波包碰撞后的干涉过程", output_root=tmp_path)
    assert result.outcome is AgentRunOutcome.READY
    assert result.animation_ir is not None
    mutated = result.animation_ir.model_copy(update={"pattern": VisualPattern.COMPARISON})
    source = compile_animation_ir(mutated, result.tool_runs).segments[0].source
    assert "ImageMobject" in source
    assert "set_height(6.0)" in source
    assert "polyline" not in source
    assert validate_source_security(source).allowed


def test_array_names_do_not_collide_with_object_ids(tmp_path: Path) -> None:
    lorenz = run_agent("展示三个初值只差 1e-5 的 Lorenz 轨迹分离", output_root=tmp_path)
    lorenz_src = compile_animation_ir(lorenz.animation_ir, lorenz.tool_runs).segments[0].source
    assert "paths_arr = packed['paths']" in lorenz_src
    assert "len(paths_arr[0]) - 1" in lorenz_src
    assert validate_source_security(lorenz_src).allowed

    frenet = run_agent("展示三维螺旋线上的切向量法向量副法向量", output_root=tmp_path)
    frenet_src = compile_animation_ir(frenet.animation_ir, frenet.tool_runs).segments[0].source
    assert "curve_arr = packed['curve']" in frenet_src
    assert "scaled(curve_arr[index])" in frenet_src
    assert "set_value(len(curve_arr) - 1)" in frenet_src
    assert validate_source_security(frenet_src).allowed
