from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from manim_workbench_contracts import RenderJobFailureCode
from manim_workbench_contracts.models import RenderArtifactPayload
from manim_workbench_runner.rendering.executor import (
    CommandRunner,
    CommandTimedOut,
    SubprocessCommandRunner,
)
from manim_workbench_runner.rendering.models import PROFILE_CONFIGS

from .artifacts import ArtifactValidationError, publish_output, validate_output_directory
from .policy import SandboxInvocation, SandboxLimits, build_sandbox_command, derive_container_name


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
        limits: SandboxLimits | None = None,
        docker_command: Sequence[str] = ("docker",),
    ) -> None:
        self.command_runner = command_runner or SubprocessCommandRunner()
        self.limits = limits or SandboxLimits()
        self.docker_command = tuple(docker_command)

    def execute(
        self,
        invocation: SandboxInvocation,
        *,
        publish_directory: Path | None = None,
        allowed_publish_root: Path | None = None,
    ) -> SandboxExecutionResult:
        command = build_sandbox_command(
            invocation,
            self.limits,
            docker_command=self.docker_command,
        )
        container_name = self._container_name_from_run(command)
        try:
            result = self.command_runner.run(
                command,
                timeout_seconds=self._timeout_seconds(invocation),
            )
        except CommandTimedOut:
            self._cleanup(container_name)
            return SandboxExecutionFailure(
                succeeded=False,
                code=RenderJobFailureCode.SANDBOX_TIMEOUT,
                message="sandbox execution exceeded its time limit",
                exit_code=None,
            )

        if result.returncode != 0:
            return SandboxExecutionFailure(
                succeeded=False,
                code=self._failure_code_for_exit(result.returncode),
                message="sandboxed renderer exited unsuccessfully",
                exit_code=result.returncode,
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
