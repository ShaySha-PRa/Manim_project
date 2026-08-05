from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class MediaAnalysisError(ValueError):
    """A stable, intentionally non-sensitive failure returned to the parent pipeline."""

    def __init__(self, code: str) -> None:
        super().__init__(code.replace("_", " "))
        self.code = code


@dataclass(frozen=True, slots=True)
class MediaMetadata:
    byte_size: int
    width: int
    height: int
    frame_count: int
    duration_seconds: float
    fps: float


@dataclass(frozen=True, slots=True)
class FrameSample:
    index: int
    timestamp_seconds: float
    width: int
    height: int
    pixels: bytes


@dataclass(frozen=True, slots=True)
class ExpectedObjectProxy:
    """A safe, renderer-produced color proxy for a planned visual object."""

    object_id: str
    rgb: tuple[int, int, int]
    min_visible_pixels: int

    def __post_init__(self) -> None:
        if not self.object_id.isidentifier() or not self.object_id.isascii():
            raise ValueError("object_id must be an ASCII identifier")
        if any(value < 0 or value > 255 for value in self.rgb):
            raise ValueError("rgb values must be in [0, 255]")
        if self.min_visible_pixels < 1:
            raise ValueError("min_visible_pixels must be positive")


@dataclass(frozen=True, slots=True)
class VisualLimits:
    sample_count: int = 24
    max_media_bytes: int = 512 * 1024 * 1024
    max_frame_count: int = 18_000
    max_duration_seconds: float = 300.0
    max_pixels_per_frame: int = 8_294_400
    max_analysis_seconds: float = 8.0
    static_threshold_seconds: float = 5.0
    contrast_delta: int = 48
    blank_active_ratio: float = 0.001
    edge_contact_pixels: int = 4
    overlap_cell_size: int = 32
    min_small_text_components: int = 80
    min_tofu_components: int = 3

    def __post_init__(self) -> None:
        if self.sample_count < 1:
            raise ValueError("sample_count must be positive")
        if self.max_media_bytes < 1 or self.max_frame_count < 1:
            raise ValueError("media limits must be positive")
        if self.max_duration_seconds <= 0 or self.max_pixels_per_frame < 1:
            raise ValueError("frame limits must be positive")
        if self.max_analysis_seconds <= 0 or self.static_threshold_seconds <= 0:
            raise ValueError("time limits must be positive")
        if not 1 <= self.contrast_delta <= 255:
            raise ValueError("contrast_delta must be in [1, 255]")
        if not 0 <= self.blank_active_ratio <= 1:
            raise ValueError("blank_active_ratio must be in [0, 1]")
        if self.edge_contact_pixels < 1 or self.overlap_cell_size < 2:
            raise ValueError("visual thresholds are invalid")
        if self.min_small_text_components < 1 or self.min_tofu_components < 1:
            raise ValueError("component thresholds must be positive")


@dataclass(frozen=True, slots=True)
class VisualDiagnostic:
    code: str
    severity: str
    evidence_ref: str
    summary: str
    measured_value: float | int | None = None
    threshold_value: float | int | None = None


@dataclass(frozen=True, slots=True)
class VisualEvidence:
    reference: str
    sampled_frame_indices: tuple[int, ...]
    summary: str


@dataclass(frozen=True, slots=True)
class VisualAnalysisResult:
    diagnostics: tuple[VisualDiagnostic, ...]
    evidence: tuple[VisualEvidence, ...]
    signature: str
    sampled_frame_indices: tuple[int, ...]


def validate_relative_media_path(media_root: Path, relative_media_path: Path) -> Path:
    """Reject traversal and existing symlinks without resolving or exposing host paths."""
    if media_root.is_symlink():
        raise MediaAnalysisError("unsafe_media_path")
    try:
        root_mode = media_root.stat().st_mode
    except OSError:
        raise MediaAnalysisError("unsafe_media_path") from None
    if not stat.S_ISDIR(root_mode):
        raise MediaAnalysisError("unsafe_media_path")
    posix = PurePosixPath(relative_media_path.as_posix())
    if relative_media_path.is_absolute() or not posix.parts or ".." in posix.parts:
        raise MediaAnalysisError("unsafe_media_path")

    current = media_root
    for part in posix.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            break
        except OSError:
            raise MediaAnalysisError("unsafe_media_path") from None
        if stat.S_ISLNK(mode):
            raise MediaAnalysisError("unsafe_media_path")
    return Path(*posix.parts)
