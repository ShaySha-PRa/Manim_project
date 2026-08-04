from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from manim_workbench_contracts import RenderJobFailureCode, RenderProfile
from manim_workbench_runner.rendering.executor import CommandResult, CommandTimedOut


class FakeCommandRunner:
    def __init__(self, responses: list[CommandResult | Exception]) -> None:
        self.responses = responses
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: Sequence[str], *, timeout_seconds: int) -> CommandResult:
        self.commands.append(tuple(command))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _result(command: Sequence[str], returncode: int = 0) -> CommandResult:
    return CommandResult(tuple(command), returncode, "docker output", 0.1)


def _invocation(tmp_path: Path):
    from manim_workbench_runner.sandbox.policy import SandboxInvocation

    source = tmp_path / "scene.py"
    source.write_text("from manim import Scene\n", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    return SandboxInvocation(
        UUID("12345678-1234-5678-1234-567812345678"),
        source,
        output,
        "GeneratedScene",
        RenderProfile.PREVIEW,
    )


def _write_expected_artifacts(output: Path) -> None:
    for name in ("video.mp4", "thumbnail.jpg", "render.log", "metadata.json"):
        (output / name).write_bytes(name.encode("ascii"))


def test_executor_returns_closed_timeout_failure_after_stop_kill_remove_and_absence_check(
    tmp_path: Path,
) -> None:
    from manim_workbench_runner.sandbox.executor import SandboxExecutor

    timeout = CommandTimedOut(("docker", "run"), "partial output")
    runner = FakeCommandRunner(
        [
            timeout,
            _result(("docker", "stop"), 0),
            _result(("docker", "kill"), 0),
            _result(("docker", "rm"), 0),
            _result(("docker", "inspect"), 1),
        ]
    )
    executor = SandboxExecutor(command_runner=runner)

    result = executor.execute(_invocation(tmp_path))

    assert result.succeeded is False
    assert result.code is RenderJobFailureCode.SANDBOX_TIMEOUT
    container_name = runner.commands[0][runner.commands[0].index("--name") + 1]
    assert container_name == "manim-wb-12345678123456781234567812345678"
    assert runner.commands[1] == ("docker", "stop", "--time", "5", container_name)
    assert runner.commands[2] == ("docker", "kill", container_name)
    assert runner.commands[3] == ("docker", "rm", "--force", container_name)
    assert runner.commands[4] == ("docker", "container", "inspect", container_name)


def test_executor_cancellation_uses_cleanup_and_returns_cancelled_outcome(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.executor import SandboxExecutor

    runner = FakeCommandRunner(
        [
            _result(("docker", "stop"), 0),
            _result(("docker", "kill"), 0),
            _result(("docker", "rm"), 0),
            _result(("docker", "inspect"), 1),
        ]
    )
    executor = SandboxExecutor(command_runner=runner)

    result = executor.cancel(_invocation(tmp_path))

    assert result.cancelled is True
    assert all(command[0] == "docker" for command in runner.commands)


def test_executor_keeps_expected_render_failure_structured(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.executor import SandboxExecutor

    runner = FakeCommandRunner([_result(("docker", "run"), 1)])
    executor = SandboxExecutor(command_runner=runner)

    result = executor.execute(_invocation(tmp_path))

    assert result.succeeded is False
    assert result.code is RenderJobFailureCode.RENDER_FAILED
    assert result.exit_code == 1


def test_executor_rejects_invalid_output_as_a_closed_publish_failure(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.executor import SandboxExecutor

    invocation = _invocation(tmp_path)
    (invocation.output_path / "unexpected.txt").write_text("unsafe", encoding="utf-8")
    runner = FakeCommandRunner([_result(("docker", "run"), 0)])

    result = SandboxExecutor(command_runner=runner).execute(invocation)

    assert result.succeeded is False
    assert result.code is RenderJobFailureCode.ARTIFACT_PUBLISH_FAILED


def test_executor_returns_validated_artifacts_on_success(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.executor import SandboxExecutor

    invocation = _invocation(tmp_path)
    _write_expected_artifacts(invocation.output_path)
    runner = FakeCommandRunner([_result(("docker", "run"), 0)])

    result = SandboxExecutor(command_runner=runner).execute(invocation)

    assert result.succeeded is True
    assert len(result.artifacts) == 4
