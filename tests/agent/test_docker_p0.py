import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from manim_workbench_api.agent.orchestrator import run_agent
from manim_workbench_api.compiler.manim import compile_animation_ir
from manim_workbench_contracts import RenderProfile
from manim_workbench_contracts.intent import AgentRunOutcome
from manim_workbench_runner.rendering.models import MANIM_IMAGE
from manim_workbench_runner.sandbox.executor import SandboxExecutionSuccess, SandboxExecutor
from manim_workbench_runner.sandbox.policy import SandboxInvocation, SandboxLimits


def _docker_ready() -> bool:
    probe = subprocess.run(
        ["docker", "image", "inspect", MANIM_IMAGE],
        check=False,
        capture_output=True,
        text=True,
    )
    return probe.returncode == 0


def _csv() -> str:
    rows = ["time,temperature,pressure"]
    for second in range(0, 401, 10):
        bump = 8.0 if 330 <= second <= 370 else 0.0
        rows.append(f"{second},{22 + bump},{1.0 + bump / 20}")
    return "\n".join(rows)


PROMPTS = (
    ("wave", "展示二维波动方程中两个波包碰撞后的干涉过程", None),
    ("fourier", "展示傅里叶级数逐渐逼近方波并放大 Gibbs 现象", None),
    ("lorenz", "展示三个初值只差 1e-5 的 Lorenz 轨迹分离", None),
    ("pid", "展示 PID 参数改变时二阶系统阶跃响应", None),
    ("csv", "从 CSV 展示 temperature 并突出 350 秒附近异常", _csv()),
    ("frenet", "展示三维螺旋线上的切向量法向量副法向量", None),
)


@pytest.mark.skipif(not _docker_ready(), reason="Docker Manim image is not present")
def test_p0_docker_renders_at_least_four_slices(tmp_path: Path) -> None:
    passed = 0
    failures: list[str] = []
    executor = SandboxExecutor(
        limits=SandboxLimits(allowed_source_root=tmp_path, allowed_output_root=tmp_path)
    )
    for name, prompt, csv_text in PROMPTS:
        compute_dir = tmp_path / name / "compute"
        result = run_agent(prompt, csv_text=csv_text, output_root=compute_dir)
        if result.outcome is not AgentRunOutcome.READY or result.animation_ir is None:
            failures.append(f"{name}: {result.outcome} {result.message}")
            continue
        source = compile_animation_ir(result.animation_ir, result.tool_runs).segments[0].source
        job_dir = tmp_path / name
        source_path = job_dir / "scene.py"
        output_dir = job_dir / "output"
        assets_dir = job_dir / "assets"
        output_dir.mkdir(parents=True)
        assets_dir.mkdir(parents=True)
        source_path.write_text(source, encoding="utf-8")
        artifact = Path(result.tool_runs[0].artifact_path)
        shutil.copyfile(artifact, assets_dir / f"{result.tool_runs[0].output_sha256}.npz")
        invocation = SandboxInvocation(
            job_id=uuid4(),
            source_path=source_path,
            output_path=output_dir,
            scene_class="GeneratedScene",
            profile=RenderProfile.PREVIEW,
            assets_path=assets_dir,
        )
        rendered = executor.execute(invocation)
        if isinstance(rendered, SandboxExecutionSuccess) and (output_dir / "video.mp4").exists():
            passed += 1
        else:
            failures.append(f"{name}: {rendered}")
    assert passed >= 4, f"only {passed} slices rendered; {failures}"
