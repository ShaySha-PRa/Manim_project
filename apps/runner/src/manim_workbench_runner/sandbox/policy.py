from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from manim_workbench_contracts import RenderProfile

from manim_workbench_runner.rendering.models import MANIM_IMAGE, PROFILE_CONFIGS

SANDBOX_ENTRYPOINT = "python"
SANDBOX_USER = "1000:1000"
HOST_FONT_ROOT = Path("/usr/share/fonts")
SANDBOX_FONT_ROOT = "/usr/share/fonts/host"
FINAL_MEMORY_LIMIT = "2g"
_SCENE_CLASS_PATTERN = re.compile(r"[A-Z][A-Za-z0-9]{1,99}")

FIXED_WRAPPER = r"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import av

profile, quality, scene_class = sys.argv[1:]
output = Path("/output")
media = output / ".media"
manim_command = [
    "manim",
    f"-q{quality}",
    "--renderer",
    "cairo",
    "--seed",
    "0",
    "--media_dir",
    str(media),
    "--output_file",
    "video",
    "/input/scene.py",
    scene_class,
]
completed = subprocess.run(
    manim_command,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    shell=False,
    check=False,
)
(output / "render.log").write_text(completed.stdout or "", encoding="utf-8")
if completed.returncode != 0:
    raise SystemExit(completed.returncode)

videos = sorted(media.rglob("video.mp4"))
if len(videos) != 1:
    raise RuntimeError("Manim did not produce exactly one video.mp4")
video = output / "video.mp4"
shutil.move(str(videos[0]), str(video))
shutil.rmtree(media)

with av.open(str(video)) as container:
    stream = container.streams.video[0]
    selected = None
    for frame in container.decode(stream):
        selected = frame
        break
    if selected is None:
        raise RuntimeError("rendered video has no decodable frame")
    selected.to_image().save(str(output / "thumbnail.jpg"), quality=85)

(output / "metadata.json").write_text(
    json.dumps(
        {"profile": profile, "scene_class": scene_class, "wrapper": "phase5-sandbox-v1"},
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)
allowed = {"video.mp4", "thumbnail.jpg", "render.log", "metadata.json"}
if {entry.name for entry in output.iterdir()} != allowed:
    raise RuntimeError("sandbox output contains an unexpected entry")
""".strip()


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
    cpuset_cpu: int = 0
    tmpfs_size: str = "256m"
    home_tmpfs_size: str = "64m"
    max_output_bytes: int = 512 * 1024 * 1024
    allowed_source_root: Path | None = None
    allowed_output_root: Path | None = None

    def __post_init__(self) -> None:
        if (
            self.pids_limit != 64
            or self.cpus != "1.0"
            or self.memory != "1g"
            or self.memory_swap != "1g"
        ):
            raise ValueError("Phase 5 sandbox resource limits are fixed")
        if not 0 <= self.cpuset_cpu <= 7:
            raise ValueError("sandbox CPU slot must be within the trusted 0..7 pool")
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
    font_root = _resolve_existing(
        HOST_FONT_ROOT,
        field_name="host_font_root",
        expect_directory=True,
    )
    profile = PROFILE_CONFIGS[invocation.profile]
    memory_limit = (
        FINAL_MEMORY_LIMIT if invocation.profile is RenderProfile.FINAL else limits.memory
    )
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
        "--cpuset-cpus",
        str(limits.cpuset_cpu),
        "--memory",
        memory_limit,
        "--memory-swap",
        memory_limit,
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size={limits.tmpfs_size}",
        "--tmpfs",
        f"/home/manim:rw,noexec,nosuid,nodev,size={limits.home_tmpfs_size}",
        "--env",
        "HOME=/home/manim",
        "--env",
        "OPENBLAS_NUM_THREADS=1",
        "--env",
        "OMP_NUM_THREADS=1",
        "--env",
        "MKL_NUM_THREADS=1",
        "--env",
        "NUMEXPR_NUM_THREADS=1",
        "--env",
        "BLIS_NUM_THREADS=1",
        "--volume",
        f"{source}:/input/scene.py:ro",
        "--volume",
        f"{output}:/output:rw",
        "--volume",
        f"{font_root}:{SANDBOX_FONT_ROOT}:ro",
        "--workdir",
        "/input",
        "--entrypoint",
        SANDBOX_ENTRYPOINT,
        MANIM_IMAGE,
        "-c",
        FIXED_WRAPPER,
        invocation.profile.value,
        profile.quality,
        invocation.scene_class,
    )
