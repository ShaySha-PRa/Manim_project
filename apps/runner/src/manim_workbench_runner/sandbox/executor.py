from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from manim_workbench_contracts import RenderJobFailureCode
from manim_workbench_contracts.models import RenderArtifactPayload

from manim_workbench_runner.rendering.executor import (
    CommandResult,
    CommandRunner,
    CommandTimedOut,
    SubprocessCommandRunner,
)
from manim_workbench_runner.rendering.models import PROFILE_CONFIGS

from .artifacts import ArtifactValidationError, publish_output, validate_output_directory
from .policy import SandboxInvocation, SandboxLimits, build_sandbox_command, derive_container_name

ControlProbe = Callable[[], bool]
CleanupCallback = Callable[[], None]


class SandboxCommandCancelled(Exception):
    """A control probe invalidated the active lease while the command was running."""


class ControlledProcessRunner(Protocol):
    """Runs a command while allowing the caller to revoke its lease without waiting."""

    def run(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: int,
        control_probe: ControlProbe | None,
        poll_interval_seconds: float,
        on_cancel: CleanupCallback,
        on_timeout: CleanupCallback,
    ) -> CommandResult: ...


class SubprocessControlledProcessRunner:
    """Popen-backed runner that checks control state while Docker is still executing."""

    def run(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: int,
        control_probe: ControlProbe | None,
        poll_interval_seconds: float,
        on_cancel: CleanupCallback,
        on_timeout: CleanupCallback,
    ) -> CommandResult:
        if timeout_seconds < 1 or poll_interval_seconds <= 0:
            raise ValueError("timeout and poll interval must be positive")
        started = time.perf_counter()
        process = subprocess.Popen(
            list(command),
            cwd=Path.cwd(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        deadline = started + timeout_seconds
        while process.poll() is None:
            if control_probe is not None and not control_probe():
                try:
                    on_cancel()
                finally:
                    self._terminate_client(process)
                raise SandboxCommandCancelled()
            if time.perf_counter() >= deadline:
                try:
                    on_timeout()
                finally:
                    output = self._terminate_client(process)
                raise CommandTimedOut(command, output)
            time.sleep(min(poll_interval_seconds, max(0.0, deadline - time.perf_counter())))
        output, _ = process.communicate()
        return CommandResult(
            command=tuple(command),
            returncode=process.returncode,
            output=output or "",
            duration_seconds=time.perf_counter() - started,
        )

    @staticmethod
    def _terminate_client(process: subprocess.Popen[str]) -> str:
        try:
            output, _ = process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate()
        return output or ""


@dataclass(frozen=True, slots=True)
class SandboxExecutionSuccess:
    succeeded: Literal[True]
    container_name: str
    duration_seconds: float
    artifacts: tuple[RenderArtifactPayload, ...]


@dataclass(frozen=True, slots=True)
class SandboxExecutionFailure:
    succeeded: Literal[False]
    code: RenderJobFailureCode
    message: str
    exit_code: int | None
    diagnostic: str | None = None


@dataclass(frozen=True, slots=True)
class SandboxExecutionCancelled:
    succeeded: Literal[False] = False
    cancelled: Literal[True] = True


SandboxExecutionResult = (
    SandboxExecutionSuccess | SandboxExecutionFailure | SandboxExecutionCancelled
)


class SandboxCleanupError(RuntimeError):
    """The daemon could not prove that an untrusted container no longer exists."""


class SandboxExecutor:
    """Run one policy-constrained attempt and make cleanup independently repeatable."""

    def __init__(
        self,
        *,
        command_runner: CommandRunner | None = None,
        controlled_process_runner: ControlledProcessRunner | None = None,
        limits: SandboxLimits | None = None,
        docker_command: Sequence[str] = ("docker",),
        control_poll_interval_seconds: float = 0.25,
    ) -> None:
        if control_poll_interval_seconds <= 0:
            raise ValueError("control_poll_interval_seconds must be positive")
        self.command_runner = command_runner or SubprocessCommandRunner()
        self.controlled_process_runner = (
            controlled_process_runner or SubprocessControlledProcessRunner()
        )
        self.limits = limits or SandboxLimits()
        self.docker_command = tuple(docker_command)
        self.control_poll_interval_seconds = control_poll_interval_seconds

    def execute(
        self,
        invocation: SandboxInvocation,
        *,
        publish_directory: Path | None = None,
        allowed_publish_root: Path | None = None,
        control_probe: ControlProbe | None = None,
    ) -> SandboxExecutionResult:
        command = build_sandbox_command(
            invocation,
            self.limits,
            docker_command=self.docker_command,
        )
        container_name = self._container_name_from_run(command)
        output_limit_exceeded = False

        def bounded_control_probe() -> bool:
            nonlocal output_limit_exceeded
            if self._output_size(invocation.output_path) > self.limits.max_output_bytes:
                output_limit_exceeded = True
                return False
            return control_probe() if control_probe is not None else True

        if control_probe is not None and not control_probe():
            self._cleanup(container_name)
            return SandboxExecutionCancelled()
        try:
            result = self.controlled_process_runner.run(
                command,
                timeout_seconds=self._timeout_seconds(invocation),
                control_probe=bounded_control_probe,
                poll_interval_seconds=self.control_poll_interval_seconds,
                on_cancel=lambda: self._cleanup(container_name),
                on_timeout=lambda: self._cleanup(container_name),
            )
        except CommandTimedOut:
            return SandboxExecutionFailure(
                succeeded=False,
                code=RenderJobFailureCode.SANDBOX_TIMEOUT,
                message="sandbox execution exceeded its time limit",
                exit_code=None,
            )
        except SandboxCommandCancelled:
            if output_limit_exceeded:
                return SandboxExecutionFailure(
                    succeeded=False,
                    code=RenderJobFailureCode.SANDBOX_OUTPUT_LIMIT,
                    message="sandbox output exceeded its size limit",
                    exit_code=None,
                )
            return SandboxExecutionCancelled()

        if result.returncode != 0:
            return SandboxExecutionFailure(
                succeeded=False,
                code=self._failure_code_for_exit(result.returncode),
                message="sandboxed renderer exited unsuccessfully",
                exit_code=result.returncode,
                diagnostic=self._read_failed_render_log(
                    invocation.output_path, fallback=result.output
                ),
            )
        try:
            artifacts = self._validate_or_publish(
                invocation,
                publish_directory=publish_directory,
                allowed_publish_root=allowed_publish_root,
            )
        except ArtifactValidationError:
            return SandboxExecutionFailure(
                succeeded=False,
                code=RenderJobFailureCode.ARTIFACT_PUBLISH_FAILED,
                message="sandbox output did not satisfy the artifact policy",
                exit_code=None,
            )
        return SandboxExecutionSuccess(
            succeeded=True,
            container_name=container_name,
            duration_seconds=result.duration_seconds,
            artifacts=artifacts,
        )

    def cancel(self, invocation: SandboxInvocation) -> SandboxExecutionCancelled:
        self._cleanup(derive_container_name(invocation))
        return SandboxExecutionCancelled()

    def _timeout_seconds(self, invocation: SandboxInvocation) -> int:
        return PROFILE_CONFIGS[invocation.profile].timeout_seconds

    def _validate_or_publish(
        self,
        invocation: SandboxInvocation,
        *,
        publish_directory: Path | None,
        allowed_publish_root: Path | None,
    ) -> tuple[RenderArtifactPayload, ...]:
        if publish_directory is None and allowed_publish_root is None:
            return validate_output_directory(
                invocation.output_path,
                max_total_bytes=self.limits.max_output_bytes,
            )
        if publish_directory is None or allowed_publish_root is None:
            raise ArtifactValidationError(
                "publish destination and allowed root must be supplied together"
            )
        return publish_output(
            invocation.output_path,
            publish_directory,
            allowed_publish_root=allowed_publish_root,
            max_total_bytes=self.limits.max_output_bytes,
        )

    def _cleanup(self, container_name: str) -> None:
        cleanup_commands = (
            (*self.docker_command, "stop", "--time", "5", container_name),
            (*self.docker_command, "kill", container_name),
            (*self.docker_command, "rm", "--force", container_name),
        )
        cleanup_errors: list[Exception] = []
        for command in cleanup_commands:
            try:
                self.command_runner.run(command, timeout_seconds=10)
            except (CommandTimedOut, FileNotFoundError) as exc:
                cleanup_errors.append(exc)
        try:
            inspection = self.command_runner.run(
                (*self.docker_command, "container", "inspect", container_name),
                timeout_seconds=10,
            )
        except (CommandTimedOut, FileNotFoundError) as exc:
            raise SandboxCleanupError("could not verify sandbox removal") from exc
        if cleanup_errors or inspection.returncode == 0:
            raise SandboxCleanupError("sandbox container may still exist")

    @staticmethod
    def _output_size(root: Path) -> int:
        total = 0
        try:
            for path in root.rglob("*"):
                if path.is_symlink():
                    continue
                if path.is_file():
                    total += path.stat().st_size
        except OSError:
            return 2**63 - 1
        return total

    @staticmethod
    def _container_name_from_run(command: Sequence[str]) -> str:
        try:
            return command[command.index("--name") + 1]
        except (ValueError, IndexError) as exc:
            raise SandboxCleanupError("sandbox run command is missing its container name") from exc

    @staticmethod
    def _failure_code_for_exit(returncode: int) -> RenderJobFailureCode:
        if returncode == 137:
            return RenderJobFailureCode.SANDBOX_OOM
        return RenderJobFailureCode.RENDER_FAILED

    @staticmethod
    def _read_failed_render_log(output_path: Path, *, fallback: str) -> str:
        log_path = output_path / "render.log"
        try:
            if log_path.is_symlink() or not log_path.is_file():
                return fallback[:20_000]
            with log_path.open(encoding="utf-8", errors="replace") as handle:
                return handle.read(20_000)
        except OSError:
            return fallback[:20_000]
