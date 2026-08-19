import json
from pathlib import Path

from manim_workbench_api.agent.orchestrator import run_agent
from manim_workbench_api.compiler.base import UnsupportedFeature
from manim_workbench_api.compiler.manim import compile_animation_ir, renderer_registry
from manim_workbench_api.compiler.web import WebBackend
from manim_workbench_contracts.intent import AgentRunOutcome


def test_web_backend_lowers_the_same_ir_to_json(tmp_path: Path) -> None:
    result = run_agent("展示傅里叶级数逐渐逼近方波并放大 Gibbs 现象", output_root=tmp_path)
    assert result.outcome is AgentRunOutcome.READY
    assert result.animation_ir is not None
    manim = compile_animation_ir(result.animation_ir, result.tool_runs, backend="manim")
    web = compile_animation_ir(result.animation_ir, result.tool_runs, backend="web")
    assert "class GeneratedScene(MovingCameraScene)" in manim.segments[0].source
    payload = json.loads(web.segments[0].source)
    assert payload["backend"] == "web"
    assert payload["scene_base"] == "WebScene"
    assert payload["data"]
    assert "lambda" not in web.segments[0].source
    assert "from manim" not in web.segments[0].source.lower()


def test_compile_cache_returns_identical_source(tmp_path: Path) -> None:
    result = run_agent("展示三个初值只差 1e-5 的 Lorenz 轨迹分离", output_root=tmp_path)
    assert result.outcome is AgentRunOutcome.READY
    assert result.animation_ir is not None
    cache = tmp_path / "ir-cache"
    first = compile_animation_ir(
        result.animation_ir, result.tool_runs, backend="web", cache_root=cache
    )
    second = compile_animation_ir(
        result.animation_ir, result.tool_runs, backend="web", cache_root=cache
    )
    assert first.segments[0].source == second.segments[0].source
    assert list(cache.glob("*.json"))


def test_unknown_renderer_hint_fails_closed() -> None:
    backend = renderer_registry.require("web")
    assert isinstance(backend, WebBackend)
    try:
        renderer_registry.require("blender")
    except UnsupportedFeature as error:
        assert "unknown renderer" in str(error)
    else:
        raise AssertionError("unknown backends must fail closed")
