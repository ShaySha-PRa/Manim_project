import sys
import time
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

import pytest
from manim_workbench_contracts import RenderJobFailureCode, RenderProfile
from manim_workbench_runner.rendering.executor import CommandResult, CommandTimedOut


class FakeCommandRunner:
    def __init__(self, responses: list[CommandResult | Exception]) -> None:
        self.responses = responses
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: int,
        control_probe=None,
        poll_interval_seconds: float | None = None,
        on_cancel=None,
        on_timeout=None,
    ) -> CommandResult:
        self.commands.append(tuple(command))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            if isinstance(response, CommandTimedOut) and on_timeout is not None:
                on_timeout()
            raise response
        return response


class BlockingControlledProcessRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.probe_calls = 0

    def run(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: int,
        control_probe,
        poll_interval_seconds: float,
        on_cancel,
        on_timeout,
    ) -> CommandResult:
        from manim_workbench_runner.sandbox.executor import SandboxCommandCancelled

        current = tuple(command)
        self.commands.append(current)
        assert control_probe is not None
        while True:
            self.probe_calls += 1
            if not control_probe():
                on_cancel()
                raise SandboxCommandCancelled()
            time.sleep(poll_interval_seconds)


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
    executor = SandboxExecutor(command_runner=runner, controlled_process_runner=runner)

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
    executor = SandboxExecutor(command_runner=runner, controlled_process_runner=runner)

    result = executor.cancel(_invocation(tmp_path))

    assert result.cancelled is True
    assert all(command[0] == "docker" for command in runner.commands)


def test_executor_keeps_expected_render_failure_structured(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.executor import SandboxExecutor

    invocation = _invocation(tmp_path)
    (invocation.output_path / "render.log").write_text(
        "Manim traceback\nValueError: invalid formula", encoding="utf-8"
    )
    runner = FakeCommandRunner([_result(("docker", "run"), 1)])
    executor = SandboxExecutor(command_runner=runner, controlled_process_runner=runner)

    result = executor.execute(invocation)

    assert result.succeeded is False
    assert result.code is RenderJobFailureCode.RENDER_FAILED
    assert result.exit_code == 1
    assert result.diagnostic == "Manim traceback\nValueError: invalid formula"


def test_executor_never_reads_a_symlinked_failed_render_log(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.executor import SandboxExecutor

    invocation = _invocation(tmp_path)
    secret = tmp_path / "outside-secret.txt"
    secret.write_text("must not be read", encoding="utf-8")
    (invocation.output_path / "render.log").symlink_to(secret)
    runner = FakeCommandRunner([_result(("docker", "run"), 1)])

    result = SandboxExecutor(
        command_runner=runner, controlled_process_runner=runner
    ).execute(invocation)

    assert result.succeeded is False
    assert result.diagnostic == "docker output"


def test_executor_rejects_invalid_output_as_a_closed_publish_failure(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.executor import SandboxExecutor

    invocation = _invocation(tmp_path)
    (invocation.output_path / "unexpected.txt").write_text("unsafe", encoding="utf-8")
    runner = FakeCommandRunner([_result(("docker", "run"), 0)])

    result = SandboxExecutor(
        command_runner=runner,
        controlled_process_runner=runner,
    ).execute(invocation)

    assert result.succeeded is False
    assert result.code is RenderJobFailureCode.ARTIFACT_PUBLISH_FAILED


def test_executor_returns_validated_artifacts_on_success(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.executor import SandboxExecutor

    invocation = _invocation(tmp_path)
    _write_expected_artifacts(invocation.output_path)
    runner = FakeCommandRunner([_result(("docker", "run"), 0)])

    result = SandboxExecutor(
        command_runner=runner,
        controlled_process_runner=runner,
    ).execute(invocation)

    assert result.succeeded is True
    assert isinstance(result.artifacts, tuple)
    assert len(result.artifacts) == 4


def test_executor_polls_control_and_cleans_up_active_container_on_cancellation(
    tmp_path: Path,
) -> None:
    from manim_workbench_runner.sandbox.executor import SandboxExecutor

    invocation = _invocation(tmp_path)
    process_runner = BlockingControlledProcessRunner()
    cleanup_runner = FakeCommandRunner(
        [
            _result(("docker", "stop"), 0),
            _result(("docker", "kill"), 0),
            _result(("docker", "rm"), 0),
            _result(("docker", "inspect"), 1),
        ]
    )
    probe_results = iter((True, True, False))
    executor = SandboxExecutor(
        command_runner=cleanup_runner,
        controlled_process_runner=process_runner,
        control_poll_interval_seconds=0.001,
    )

    result = executor.execute(invocation, control_probe=lambda: next(probe_results))

    assert result.cancelled is True
    assert process_runner.probe_calls >= 2
    container_name = process_runner.commands[0][process_runner.commands[0].index("--name") + 1]
    assert ("docker", "stop", "--time", "5", container_name) in cleanup_runner.commands
    assert ("docker", "kill", container_name) in cleanup_runner.commands
    assert ("docker", "rm", "--force", container_name) in cleanup_runner.commands
    assert ("docker", "container", "inspect", container_name) in cleanup_runner.commands


def test_executor_stops_container_when_bound_output_exceeds_limit(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.executor import SandboxExecutor
    from manim_workbench_runner.sandbox.policy import SandboxLimits

    invocation = _invocation(tmp_path)
    (invocation.output_path / "oversized.bin").write_bytes(b"1234")
    process_runner = BlockingControlledProcessRunner()
    cleanup_runner = FakeCommandRunner(
        [
            _result(("docker", "stop"), 0),
            _result(("docker", "kill"), 0),
            _result(("docker", "rm"), 0),
            _result(("docker", "inspect"), 1),
        ]
    )

    result = SandboxExecutor(
        command_runner=cleanup_runner,
        controlled_process_runner=process_runner,
        limits=SandboxLimits(max_output_bytes=3),
    ).execute(invocation)

    assert result.succeeded is False
    assert result.code is RenderJobFailureCode.SANDBOX_OUTPUT_LIMIT


def test_default_controlled_runner_polls_a_live_process_multiple_times() -> None:
    from manim_workbench_runner.sandbox.executor import SubprocessControlledProcessRunner

    probe_calls = 0

    def probe() -> bool:
        nonlocal probe_calls
        probe_calls += 1
        return True

    result = SubprocessControlledProcessRunner().run(
        (sys.executable, "-c", "import time; time.sleep(0.03)"),
        timeout_seconds=1,
        control_probe=probe,
        poll_interval_seconds=0.002,
        on_cancel=lambda: pytest.fail("cancel callback must not run"),
        on_timeout=lambda: pytest.fail("timeout callback must not run"),
    )

    assert result.returncode == 0
    assert probe_calls >= 2


def test_default_controlled_runner_cancels_a_live_process_before_completion() -> None:
    from manim_workbench_runner.sandbox.executor import (
        SandboxCommandCancelled,
        SubprocessControlledProcessRunner,
    )

    probe_calls = 0
    cancelled = False

    def probe() -> bool:
        nonlocal probe_calls
        probe_calls += 1
        return probe_calls < 3

    def on_cancel() -> None:
        nonlocal cancelled
        cancelled = True

    with pytest.raises(SandboxCommandCancelled):
        SubprocessControlledProcessRunner().run(
            (sys.executable, "-c", "import time; time.sleep(1)"),
            timeout_seconds=2,
            control_probe=probe,
            poll_interval_seconds=0.002,
            on_cancel=on_cancel,
            on_timeout=lambda: pytest.fail("timeout callback must not run"),
        )

    assert cancelled is True
    assert probe_calls == 3
