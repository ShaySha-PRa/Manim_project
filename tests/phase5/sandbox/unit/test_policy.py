from pathlib import Path
from uuid import UUID

import pytest
from manim_workbench_contracts import RenderProfile


def _invocation(tmp_path: Path):
    from manim_workbench_runner.sandbox.policy import SandboxInvocation

    source = tmp_path / "sources" / "scene.py"
    source.parent.mkdir(exist_ok=True)
    source.write_text("from manim import Scene\n", encoding="utf-8")
    output = tmp_path / "attempts" / "job-output"
    output.mkdir(parents=True, exist_ok=True)
    return SandboxInvocation(
        UUID("12345678-1234-5678-1234-567812345678"),
        source,
        output,
        "GeneratedScene",
        RenderProfile.PREVIEW,
    )


def _option(command: tuple[str, ...], flag: str) -> tuple[str, str]:
    position = command.index(flag)
    return command[position : position + 2]


def test_build_sandbox_command_has_only_fixed_least_privilege_options(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.policy import SandboxLimits, build_sandbox_command

    invocation = _invocation(tmp_path)
    command = build_sandbox_command(
        invocation,
        SandboxLimits(
            allowed_source_root=tmp_path / "sources",
            allowed_output_root=tmp_path / "attempts",
        ),
    )

    assert command[:2] == ("docker", "run")
    assert "--rm" in command
    assert _option(command, "--pull") == ("--pull", "never")
    assert _option(command, "--network") == ("--network", "none")
    assert "--read-only" in command
    assert _option(command, "--cap-drop") == ("--cap-drop", "ALL")
    assert _option(command, "--security-opt") == ("--security-opt", "no-new-privileges")
    assert _option(command, "--user") == ("--user", "1000:1000")
    assert _option(command, "--pids-limit") == ("--pids-limit", "64")
    assert _option(command, "--cpus") == ("--cpus", "1.0")
    assert _option(command, "--memory") == ("--memory", "1g")
    assert _option(command, "--memory-swap") == ("--memory-swap", "1g")
    assert "/tmp:rw,noexec,nosuid,nodev,size=256m" in command
    assert "/home/manim:rw,noexec,nosuid,nodev,size=64m" in command
    assert "HOME=/home/manim" in command
    assert any(item.endswith(":/input/scene.py:ro") for item in command)
    assert any(item.endswith(":/output:rw") for item in command)
    assert "--privileged" not in command
    assert not any(item.startswith("--pid=") or item == "--pid" for item in command)
    assert not any(item.startswith("--ipc=") or item == "--ipc" for item in command)
    assert not any(item.startswith("--network=host") for item in command)
    assert not any("docker.sock" in item for item in command)
    assert not any("seccomp=unconfined" in item for item in command)
    assert command[-2:] == ("/input/scene.py", "GeneratedScene")


def test_command_uses_stable_safe_name_derived_from_job_id(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.policy import SandboxLimits, build_sandbox_command

    first = build_sandbox_command(_invocation(tmp_path), SandboxLimits())
    second = build_sandbox_command(_invocation(tmp_path), SandboxLimits())
    first_name = first[first.index("--name") + 1]
    second_name = second[second.index("--name") + 1]

    assert first_name == "manim-wb-12345678123456781234567812345678"
    assert first_name == second_name
    assert first_name.replace("-", "").isalnum()


@pytest.mark.parametrize("field", ("source", "output"))
def test_command_rejects_paths_outside_caller_allowed_roots(tmp_path: Path, field: str) -> None:
    from manim_workbench_runner.sandbox.policy import (
        SandboxInvocation,
        SandboxLimits,
        build_sandbox_command,
    )

    source = tmp_path / "outside.py"
    source.write_text("from manim import Scene\n", encoding="utf-8")
    output = tmp_path / "outside-output"
    output.mkdir()
    if field == "source":
        source_root = tmp_path / "sources"
        source_root.mkdir()
        allowed_output_root = tmp_path
    else:
        source_root = tmp_path
        allowed_output_root = tmp_path / "attempts"
        allowed_output_root.mkdir()

    uuid = UUID("12345678-1234-5678-1234-567812345678")
    invocation = SandboxInvocation(
        uuid,
        source,
        output,
        "GeneratedScene",
        RenderProfile.PREVIEW,
    )
    assert invocation.job_id == uuid
    with pytest.raises(ValueError, match="allowed"):
        build_sandbox_command(
            invocation,
            SandboxLimits(
                allowed_source_root=source_root,
                allowed_output_root=allowed_output_root,
            ),
        )


def test_command_rejects_symlink_source_and_invalid_scene_class(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.policy import (
        SandboxInvocation,
        SandboxLimits,
        build_sandbox_command,
    )

    source = tmp_path / "source.py"
    source.write_text("from manim import Scene\n", encoding="utf-8")
    linked = tmp_path / "linked.py"
    linked.symlink_to(source)
    output = tmp_path / "output"
    output.mkdir()
    uuid = UUID("12345678-1234-5678-1234-567812345678")
    invocation = SandboxInvocation(
        uuid,
        linked,
        output,
        "not-a-scene",
        RenderProfile.PREVIEW,
    )
    assert invocation.job_id == uuid

    with pytest.raises(ValueError, match="symlink|scene_class"):
        build_sandbox_command(invocation, SandboxLimits())
