"""Black-box contract tests for the Phase 5 one-shot sandbox command boundary."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from manim_workbench_contracts import RenderProfile


class CapturingExecutor:
    """Fake external process boundary that rejects shell-shaped Docker invocations."""

    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: Sequence[str]) -> None:
        argv = tuple(command)
        self.commands.append(argv)
        assert argv[0] == "docker"
        assert all("\x00" not in value for value in argv)
        assert "/bin/sh" not in argv
        assert "sh" not in argv
        assert "bash" not in argv


def sandbox_command(
    tmp_path: Path, scene_class: str = "GeneratedScene", job_id: UUID | None = None
) -> list[str]:
    from manim_workbench_runner.sandbox.policy import (
        SandboxInvocation,
        SandboxLimits,
        build_sandbox_command,
    )

    source = tmp_path / "scene.py"
    source.write_text(
        "from manim import Scene\nclass GeneratedScene(Scene): pass\n", encoding="utf-8"
    )
    output = tmp_path / "output"
    output.mkdir()
    invocation = SandboxInvocation(
        job_id or uuid4(), source, output, scene_class, RenderProfile.PREVIEW
    )
    return build_sandbox_command(invocation, SandboxLimits())


def option(command: list[str], flag: str) -> str:
    try:
        return command[command.index(flag) + 1]
    except (ValueError, IndexError) as exc:
        raise AssertionError(f"missing {flag}") from exc


def test_static_policy_has_every_required_isolation_control(tmp_path: Path) -> None:
    command = sandbox_command(tmp_path)
    joined = " ".join(command)

    assert option(command, "--network") == "none"
    assert "--read-only" in command
    assert option(command, "--cap-drop") == "ALL"
    assert option(command, "--security-opt") == "no-new-privileges"
    assert "seccomp=unconfined" not in joined
    assert option(command, "--pids-limit") == "64"
    assert option(command, "--cpus") == "1.0"
    assert option(command, "--cpuset-cpus") == "0"
    assert option(command, "--memory") == "1g"
    assert option(command, "--memory-swap") == "1g"
    assert option(command, "--pull") == "never"

    user = option(command, "--user")
    assert user not in {"0", "0:0", "root"}
    tmpfs = [command[index + 1] for index, value in enumerate(command[:-1]) if value == "--tmpfs"]
    assert "/tmp:rw,noexec,nosuid,nodev,size=256m" in tmpfs
    assert "/home/manim:rw,noexec,nosuid,nodev,size=64m" in tmpfs
    assert "HOME=/home/manim" in command

    assert "--privileged" not in command
    for forbidden in ("--pid", "--ipc", "--uts", "--userns", "/var/run/docker.sock"):
        assert forbidden not in command
    assert "docker.sock" not in joined


def test_fake_executor_observes_argv_only_fixed_mounts_and_uuid_container_name(
    tmp_path: Path,
) -> None:
    job_id = uuid4()
    command = sandbox_command(tmp_path, job_id=job_id)
    executor = CapturingExecutor()
    executor.run(command)

    assert len(executor.commands) == 1
    observed = executor.commands[0]
    name = option(list(observed), "--name")
    assert name.startswith("manim-")
    assert job_id.hex in name
    volumes = [
        observed[index + 1]
        for index, value in enumerate(observed[:-1])
        if value in {"--volume", "-v"}
    ]
    assert len(volumes) == 3
    assert any(volume.endswith(":/input/scene.py:ro") for volume in volumes)
    assert any(volume.endswith(":/output:rw") for volume in volumes)
    assert "/usr/share/fonts:/usr/share/fonts/host:ro" in volumes
    assert all("/home/" not in volume or ":/input/scene.py:ro" in volume for volume in volumes)


def test_scene_class_cannot_turn_into_shell_or_docker_argument_injection(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        sandbox_command(tmp_path, "GeneratedScene;touch /output/pwned")
