from __future__ import annotations

from pathlib import Path

from manim_workbench_api.phase7_runtime import Phase7SandboxRenderer
from manim_workbench_contracts import RenderJobFailureCode
from manim_workbench_runner.sandbox.executor import (
    SandboxExecutionFailure,
    SandboxExecutionSuccess,
)


class RecordingExecutor:
    def __init__(self, result: object) -> None:
        self.result = result
        self.invocations = []

    def execute(self, invocation):  # type: ignore[no-untyped-def]
        self.invocations.append(invocation)
        assert invocation.source_path.read_text(encoding="utf-8").startswith("from manim")
        assert invocation.output_path.is_dir()
        return self.result


def test_runtime_stages_source_under_private_root_and_cleans_attempt(tmp_path: Path) -> None:
    executor = RecordingExecutor(
        SandboxExecutionSuccess(
            succeeded=True,
            container_name="phase7-test",
            duration_seconds=0.2,
            artifacts=(),
        )
    )
    renderer = Phase7SandboxRenderer(runtime_root=tmp_path, executor=executor)
    result = renderer.render(
        "from manim import Scene\nclass GeneratedScene(Scene):\n    pass\n",
        "GeneratedScene",
    )

    assert result.succeeded is True
    assert len(executor.invocations) == 1
    assert list(tmp_path.rglob("scene.py")) == []


def test_runtime_maps_resource_and_security_failures_without_exposing_paths(
    tmp_path: Path,
) -> None:
    resource_executor = RecordingExecutor(
        SandboxExecutionFailure(
            succeeded=False,
            code=RenderJobFailureCode.SANDBOX_OOM,
            message=f"failed at {tmp_path}/secret.env",
            exit_code=137,
            diagnostic=(
                f"Traceback at {tmp_path}/scene.py\n"
                "DEEPSEEK_API_KEY=sk-1234567890abcdef\nordinary Manim error"
            ),
        )
    )
    resource = Phase7SandboxRenderer(
        runtime_root=tmp_path / "resource", executor=resource_executor
    ).render("from manim import Scene\nclass GeneratedScene(Scene): pass\n", "GeneratedScene")
    assert resource.error_code == "sandbox_resource_limit"
    assert str(tmp_path) not in resource.diagnostic
    assert "sk-1234567890abcdef" not in resource.diagnostic
    assert "ordinary Manim error" in resource.diagnostic

    security_executor = RecordingExecutor(
        SandboxExecutionFailure(
            succeeded=False,
            code=RenderJobFailureCode.SANDBOX_SECURITY_VIOLATION,
            message="policy rejected candidate",
            exit_code=None,
        )
    )
    security = Phase7SandboxRenderer(
        runtime_root=tmp_path / "security", executor=security_executor
    ).render("from manim import Scene\nclass GeneratedScene(Scene): pass\n", "GeneratedScene")
    assert security.error_code == "security_policy_violation"
