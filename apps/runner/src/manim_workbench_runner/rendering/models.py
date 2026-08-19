from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Literal

from manim_workbench_contracts import RenderProfile

RENDER_CONTRACT_VERSION = "phase4-render-v1"
MANIM_VERSION = "0.21.0"
MANIM_IMAGE = (
    "manimcommunity/manim@"
    "sha256:89ab433ce59134a4dcf351deb2511e067ab354393c0bb7d1859f3e8f0b2406a3"
)
MANIM_IMAGE_DIGEST = MANIM_IMAGE.split("@", 1)[1]


@dataclass(frozen=True, slots=True)
class RenderProfileConfig:
    name: RenderProfile
    quality: Literal["l", "h"]
    width: int
    height: int
    frame_rate: int
    timeout_seconds: int
    renderer: Literal["cairo"] = "cairo"
    seed: int = 0


PREVIEW_PROFILE = RenderProfileConfig(RenderProfile.PREVIEW, "l", 854, 480, 15, 60)
FINAL_PROFILE = RenderProfileConfig(RenderProfile.FINAL, "h", 1920, 1080, 60, 300)
PROFILE_CONFIGS = {
    RenderProfile.PREVIEW: PREVIEW_PROFILE,
    RenderProfile.FINAL: FINAL_PROFILE,
}


class RenderStage(str, Enum):
    REQUEST = "request"
    PREPARE = "prepare"
    RENDER = "render"
    PROBE = "probe"
    THUMBNAIL = "thumbnail"
    PUBLISH = "publish"


class RenderFailureCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    SOURCE_NOT_FOUND = "source_not_found"
    DOCKER_UNAVAILABLE = "docker_unavailable"
    CONTAINER_START_FAILED = "container_start_failed"
    RENDER_TIMEOUT = "render_timeout"
    MANIM_RENDER_FAILED = "manim_render_failed"
    MISSING_VIDEO = "missing_video"
    EMPTY_VIDEO = "empty_video"
    FFPROBE_FAILED = "ffprobe_failed"
    ZERO_FRAMES = "zero_frames"
    INVALID_DURATION = "invalid_duration"
    FFMPEG_FAILED = "ffmpeg_failed"
    MISSING_THUMBNAIL = "missing_thumbnail"
    ARTIFACT_IO_FAILED = "artifact_io_failed"


class RenderFailure(Exception):
    def __init__(
        self,
        code: RenderFailureCode,
        stage: RenderStage,
        message: str,
        *,
        exit_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.message = message
        self.exit_code = exit_code


def _validate_relative_path(value: Path, field_name: str) -> None:
    posix = PurePosixPath(value.as_posix())
    if value.is_absolute() or not posix.parts or ".." in posix.parts:
        raise ValueError(f"{field_name} must be a safe relative path")


@dataclass(frozen=True, slots=True)
class RenderRequest:
    scene_id: str
    scene_class: str
    source_path: Path
    profile: RenderProfile
    artifact_root: Path

    def __post_init__(self) -> None:
        if not isinstance(self.profile, RenderProfile):
            raise ValueError("profile must be a RenderProfile")
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,79}", self.scene_id):
            raise ValueError("scene_id must be lower snake case")
        if not re.fullmatch(r"[A-Z][A-Za-z0-9]{1,99}", self.scene_class):
            raise ValueError("scene_class must be a Python class name")
        _validate_relative_path(self.source_path, "source_path")
        _validate_relative_path(self.artifact_root, "artifact_root")
        if self.source_path.suffix != ".py":
            raise ValueError("source_path must identify a Python file")
        if self.profile not in PROFILE_CONFIGS:
            raise ValueError("profile is not supported")


@dataclass(frozen=True, slots=True)
class VideoProbe:
    duration_seconds: float
    frame_count: int
    width: int
    height: int
    fps: float


@dataclass(frozen=True, slots=True)
class ArtifactInfo:
    relative_path: str
    byte_size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class RenderSuccess:
    succeeded: Literal[True]
    scene_id: str
    profile: RenderProfile
    cache_key: str
    cache_hit: bool
    artifacts: dict[str, ArtifactInfo]
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class RenderFailureResult:
    succeeded: Literal[False]
    scene_id: str
    profile: RenderProfile
    code: RenderFailureCode
    stage: RenderStage
    message: str
    exit_code: int | None
    log_relative_path: str | None


RenderResult = RenderSuccess | RenderFailureResult
