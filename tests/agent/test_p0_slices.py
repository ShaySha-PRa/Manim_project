from pathlib import Path

from manim_workbench_api.agent.orchestrator import run_agent
from manim_workbench_api.code_generation.security import validate_source_security
from manim_workbench_api.compiler.manim import compile_animation_ir
from manim_workbench_contracts.intent import AgentRunOutcome


def _csv() -> str:
    rows = ["time,temperature,pressure"]
    for second in range(0, 401, 5):
        temperature = 22.0 + (8.0 if 330 <= second <= 370 else 0.0)
        pressure = 1.0 + (0.4 if 330 <= second <= 370 else 0.0)
        rows.append(f"{second},{temperature},{pressure}")
    return "\n".join(rows)


SLICES = (
    ("展示二维波动方程中两个波包碰撞后的干涉过程", None, "linear_superposition"),
    ("展示傅里叶级数逐渐逼近方波，并放大 Gibbs 现象", None, "harmonic_coefficients"),
    ("展示三个初值只差 1e-5 的 Lorenz 系统轨迹逐渐分离", None, "trajectory_error"),
    ("展示 PID 参数改变时二阶系统阶跃响应如何变化", None, "metric_match"),
    ("从 CSV 展示 temperature/pressure 并突出 350 秒附近异常", _csv(), "data_fidelity"),
    ("展示三维螺旋线上的切向量、法向量和副法向量随参数移动", None, "frenet_orthonormal"),
)


def test_p0_slices_compile_without_lambda(tmp_path: Path) -> None:
    for prompt, csv_text, assertion_key in SLICES:
        result = run_agent(prompt, csv_text=csv_text, output_root=tmp_path)
        assert result.outcome is AgentRunOutcome.READY, result.message
        assert result.animation_ir is not None
        assert result.tool_runs
        assert result.tool_runs[0].assertions.get(assertion_key) is True
        compiled = compile_animation_ir(result.animation_ir, result.tool_runs)
        source = compiled.segments[0].source
        assert "lambda" not in source
        assert "np.exp" not in source
        assert "allow_pickle=False" in source
        report = validate_source_security(source)
        assert report.allowed, report.findings
        again = compile_animation_ir(result.animation_ir, result.tool_runs).segments[0].source
        assert again == source


def test_wave_window_covers_collision_and_pass_through(tmp_path: Path) -> None:
    import numpy as np

    result = run_agent("展示二维波动方程中两个波包碰撞后的干涉过程", output_root=tmp_path)
    assert result.outcome is AgentRunOutcome.READY
    assert result.tool_runs[0].assertions.get("collision_in_window") is True
    assert result.tool_runs[0].assertions.get("pass_through") is True
    source = compile_animation_ir(result.animation_ir, result.tool_runs).segments[0].source
    assert "set_height(6.0)" in source
    assert "scale(2.4)" not in source
    packed = np.load(result.tool_runs[0].artifact_path, allow_pickle=False)
    field = packed["field"]
    xs = packed["x"]
    mid_y = field.shape[1] // 2
    abs_line = np.abs(field[:, mid_y, :])
    nx = abs_line.shape[1]
    seps = []
    for row in abs_line:
        left_i = int(np.argmax(row[: nx // 2]))
        right_i = int(nx // 2 + np.argmax(row[nx // 2 :]))
        seps.append(abs(float(xs[right_i]) - float(xs[left_i])))
    closest = int(np.argmin(seps))
    assert 0 < closest < len(seps) - 1
    assert seps[-1] > 0.5 * seps[0]


def test_lorenz_trajectories_diverge(tmp_path: Path) -> None:
    result = run_agent("展示三个初值只差 1e-5 的 Lorenz 轨迹分离", output_root=tmp_path)
    assert result.outcome is AgentRunOutcome.READY
    assert result.tool_runs[0].assertions.get("diverged") is True
    assert float(result.tool_runs[0].assertions["late_separation"]) > 1.0


def test_pid_reaches_setpoint_with_distinct_overshoot(tmp_path: Path) -> None:
    result = run_agent("展示 PID 参数改变时二阶系统阶跃响应", output_root=tmp_path)
    assert result.outcome is AgentRunOutcome.READY
    assert result.tool_runs[0].assertions.get("reached_setpoint") is True
    assert result.tool_runs[0].assertions.get("metric_match") is True
    source = compile_animation_ir(result.animation_ir, result.tool_runs).segments[0].source
    assert "DashedLine" in source
    assert "self.wait" not in source or "self.play" in source
    report = validate_source_security(source)
    assert report.allowed, report.findings


def test_fourier_zooms_into_gibbs(tmp_path: Path) -> None:
    result = run_agent("展示傅里叶级数逐渐逼近方波并放大 Gibbs 现象", output_root=tmp_path)
    assert result.outcome is AgentRunOutcome.READY
    assert result.tool_runs[0].assertions.get("gibbs_overshoot") is True
    compiled = compile_animation_ir(result.animation_ir, result.tool_runs)
    assert compiled.segments[0].scene_base == "MovingCameraScene"
    source = compiled.segments[0].source
    assert "camera.frame" in source
    report = validate_source_security(source)
    assert report.allowed, report.findings


def test_csv_highlight_uses_data_window(tmp_path: Path) -> None:
    result = run_agent(
        "从 CSV 展示 temperature 并突出 350 秒附近异常",
        csv_text=_csv(),
        output_root=tmp_path,
    )
    assert result.outcome is AgentRunOutcome.READY
    source = compile_animation_ir(result.animation_ir, result.tool_runs).segments[0].source
    assert "add_coordinates" in source
    assert "FadeIn" in source
    assert "band.animate.scale(1.0)" not in source
    report = validate_source_security(source)
    assert report.allowed, report.findings
