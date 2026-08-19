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
    from manim_workbench_runner.sandbox.policy import (
        FIXED_WRAPPER,
        SandboxLimits,
        build_sandbox_command,
    )

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
    assert _option(command, "--cpuset-cpus") == ("--cpuset-cpus", "0")
    assert _option(command, "--memory") == ("--memory", "1g")
    assert _option(command, "--memory-swap") == ("--memory-swap", "1g")
    assert "/tmp:rw,noexec,nosuid,nodev,size=256m" in command
    assert "/home/manim:rw,noexec,nosuid,nodev,size=64m" in command
    assert "HOME=/home/manim" in command
    for fixed_thread_limit in (
        "OPENBLAS_NUM_THREADS=1",
        "OMP_NUM_THREADS=1",
        "MKL_NUM_THREADS=1",
        "NUMEXPR_NUM_THREADS=1",
        "BLIS_NUM_THREADS=1",
    ):
        assert fixed_thread_limit in command
    assert any(item.endswith(":/input/scene.py:ro") for item in command)
    assert any(item.endswith(":/output:rw") for item in command)
    assert "/usr/share/fonts:/usr/share/fonts/host:ro" in command
    assert "--privileged" not in command
    assert not any(item.startswith("--pid=") or item == "--pid" for item in command)
    assert not any(item.startswith("--ipc=") or item == "--ipc" for item in command)
    assert not any(item.startswith("--network=host") for item in command)
    assert not any("docker.sock" in item for item in command)
    assert not any("seccomp=unconfined" in item for item in command)
    assert _option(command, "--entrypoint") == ("--entrypoint", "python")
    assert FIXED_WRAPPER in command
    assert "shell=False" in FIXED_WRAPPER
    assert "thumbnail.jpg" in FIXED_WRAPPER
    assert "metadata.json" in FIXED_WRAPPER
    assert command[-3:] == ("preview", "l", "GeneratedScene")


def test_command_uses_stable_safe_name_derived_from_job_id(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.policy import SandboxLimits, build_sandbox_command

    first = build_sandbox_command(_invocation(tmp_path), SandboxLimits())
    second = build_sandbox_command(_invocation(tmp_path), SandboxLimits())
    first_name = first[first.index("--name") + 1]
    second_name = second[second.index("--name") + 1]

    assert first_name == "manim-wb-12345678123456781234567812345678"
    assert first_name == second_name
    assert first_name.replace("-", "").isalnum()


def test_final_profile_has_a_fixed_bounded_memory_budget(tmp_path: Path) -> None:
    from dataclasses import replace

    from manim_workbench_runner.sandbox.policy import SandboxLimits, build_sandbox_command

    invocation = replace(_invocation(tmp_path), profile=RenderProfile.FINAL)
    command = build_sandbox_command(invocation, SandboxLimits())

    assert _option(command, "--memory") == ("--memory", "2g")
    assert _option(command, "--memory-swap") == ("--memory-swap", "2g")


def test_sandbox_limits_reject_resource_limit_overrides() -> None:
    from manim_workbench_runner.sandbox.policy import SandboxLimits

    with pytest.raises(ValueError, match="resource limits"):
        SandboxLimits(pids_limit=65)
    with pytest.raises(ValueError, match="CPU slot"):
        SandboxLimits(cpuset_cpu=8)


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


def test_three_d_memory_tier_uses_4g(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.policy import (
        SandboxInvocation,
        SandboxLimits,
        build_sandbox_command,
        memory_tier_for_source,
    )

    invocation = _invocation(tmp_path)
    three_d = SandboxInvocation(
        invocation.job_id,
        invocation.source_path,
        invocation.output_path,
        invocation.scene_class,
        invocation.profile,
        memory_tier="three_d",
    )
    command = build_sandbox_command(three_d, SandboxLimits())
    assert command[command.index("--memory") + 1] == "4g"
    assert command[command.index("--memory-swap") + 1] == "4g"
    three_d_source = (
        "class GeneratedScene(ThreeDScene):\n    def construct(self):\n        pass\n"
    )
    two_d_source = "class GeneratedScene(Scene):\n    def construct(self):\n        pass\n"
    assert memory_tier_for_source(three_d_source) == "three_d"
    assert memory_tier_for_source(two_d_source) == "standard"
