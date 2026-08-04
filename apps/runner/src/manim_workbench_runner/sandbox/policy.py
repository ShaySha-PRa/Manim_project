from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from manim_workbench_contracts import RenderProfile
from manim_workbench_runner.rendering.models import MANIM_IMAGE, PROFILE_CONFIGS

SANDBOX_ENTRYPOINT = "manim"
SANDBOX_USER = "1000:1000"
_SCENE_CLASS_PATTERN = re.compile(r"[A-Z][A-Za-z0-9]{1,99}")


@dataclass(frozen=True, slots=True)
class SandboxInvocation:
    job_id: UUID
    source_path: Path
    output_path: Path
    scene_class: str
    profile: RenderProfile


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    pids_limit: int = 64
    cpus: str = "1.0"
    memory: str = "1g"
    memory_swap: str = "1g"
    tmpfs_size: str = "256m"
    home_tmpfs_size: str = "64m"
    max_output_bytes: int = 512 * 1024 * 1024
    allowed_source_root: Path | None = None
    allowed_output_root: Path | None = None

    def __post_init__(self) -> None:
        if self.pids_limit < 1:
            raise ValueError("pids_limit must be positive")
        if self.cpus != "1.0" or self.memory != "1g" or self.memory_swap != "1g":
            raise ValueError("Phase 5 sandbox resource limits are fixed")
        if self.tmpfs_size != "256m" or self.home_tmpfs_size != "64m":
            raise ValueError("Phase 5 sandbox tmpfs limits are fixed")
        if self.max_output_bytes < 1:
            raise ValueError("max_output_bytes must be positive")


def derive_container_name(invocation: SandboxInvocation) -> str:
    """Return a stable daemon-safe name for the Job's single active lease."""
    return f"manim-wb-{invocation.job_id.hex}"


def _resolve_existing(path: Path, *, field_name: str, expect_directory: bool) -> Path:
    if path.is_symlink():
        raise ValueError(f"{field_name} must not be a symlink")
    resolved = path.resolve(strict=True)
    if expect_directory and not resolved.is_dir():
        raise ValueError(f"{field_name} must be an existing directory")
    if not expect_directory and not resolved.is_file():
        raise ValueError(f"{field_name} must be an existing regular file")
    return resolved


def _validate_under_root(path: Path, root: Path | None, *, field_name: str) -> None:
    if root is None:
        return
    resolved_root = root.resolve(strict=True)
    if not resolved_root.is_dir():
        raise ValueError(f"{field_name} allowed root must be an existing directory")
    if not path.is_relative_to(resolved_root):
        raise ValueError(f"{field_name} must stay under its caller allowed root")


def _validated_paths(invocation: SandboxInvocation, limits: SandboxLimits) -> tuple[Path, Path]:
    if (
        not isinstance(invocation.profile, RenderProfile)
        or invocation.profile not in PROFILE_CONFIGS
    ):
        raise ValueError("profile must be a supported RenderProfile")
    if not _SCENE_CLASS_PATTERN.fullmatch(invocation.scene_class):
        raise ValueError("scene_class must be a Python class name")
    source = _resolve_existing(
        invocation.source_path,
        field_name="source_path",
        expect_directory=False,
    )
    output = _resolve_existing(
        invocation.output_path,
        field_name="output_path",
        expect_directory=True,
    )
    _validate_under_root(source, limits.allowed_source_root, field_name="source_path")
    _validate_under_root(output, limits.allowed_output_root, field_name="output_path")
    return source, output


def build_sandbox_command(
    invocation: SandboxInvocation,
    limits: SandboxLimits,
    *,
    docker_command: Sequence[str] = ("docker",),
) -> tuple[str, ...]:
    """Build the only permitted argv for an untrusted one-shot Manim attempt."""
    if not docker_command:
        raise ValueError("docker_command must not be empty")
    source, output = _validated_paths(invocation, limits)
    profile = PROFILE_CONFIGS[invocation.profile]
    return (
        *docker_command,
        "run",
        "--rm",
        "--pull",
        "never",
        "--name",
        derive_container_name(invocation),
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        SANDBOX_USER,
        "--pids-limit",
        str(limits.pids_limit),
        "--cpus",
        limits.cpus,
        "--memory",
        limits.memory,
        "--memory-swap",
        limits.memory_swap,
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size={limits.tmpfs_size}",
        "--tmpfs",
        f"/home/manim:rw,noexec,nosuid,nodev,size={limits.home_tmpfs_size}",
        "--env",
        "HOME=/home/manim",
        "--volume",
        f"{source}:/input/scene.py:ro",
        "--volume",
        f"{output}:/output:rw",
        "--workdir",
        "/input",
        "--entrypoint",
        SANDBOX_ENTRYPOINT,
        MANIM_IMAGE,
        f"-q{profile.quality}",
        "--renderer",
        profile.renderer,
        "--seed",
        str(profile.seed),
        "--media_dir",
        "/output/media",
        "--output_file",
        "video",
        "/input/scene.py",
        invocation.scene_class,
    )
