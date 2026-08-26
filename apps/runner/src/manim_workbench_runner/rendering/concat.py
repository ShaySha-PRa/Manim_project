"""Validate and hard-cut independently rendered MP4 segments."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av
from manim_workbench_contracts import RenderProfile


class ConcatError(ValueError):
    """Raised when segment videos cannot be concatenated safely."""


@dataclass(frozen=True, slots=True)
class ClipInput:
    path: Path
    profile: RenderProfile
    sha256: str


@dataclass(frozen=True, slots=True)
class MediaDescriptor:
    path: Path
    profile: RenderProfile
    sha256: str
    byte_size: int
    duration_seconds: float
    frame_count: int
    width: int
    height: int
    fps: float
    pixel_format: str


@dataclass(frozen=True, slots=True)
class CompositionResult:
    path: Path
    media: MediaDescriptor
    reused_single_clip: bool


def compose_mp4s(
    inputs: tuple[ClipInput, ...],
    output: Path,
    *,
    staging_root: Path,
) -> CompositionResult:
    if not inputs:
        raise ConcatError("composition requires at least one segment")
    descriptors = tuple(inspect_clip(item) for item in inputs)
    _validate_compatible(descriptors)
    if len(descriptors) == 1:
        return CompositionResult(
            path=descriptors[0].path,
            media=descriptors[0],
            reused_single_clip=True,
        )
    safe_output = _validate_staging_output(output, staging_root)
    _encode_hard_cuts(descriptors, safe_output)
    output_input = ClipInput(
        path=safe_output,
        profile=descriptors[0].profile,
        sha256=_hash_regular_file(safe_output)[1],
    )
    output_descriptor = inspect_clip(output_input)
    expected_frames = sum(item.frame_count for item in descriptors)
    frame_tolerance = max(2, len(descriptors))
    if abs(output_descriptor.frame_count - expected_frames) > frame_tolerance:
        raise ConcatError("composed duration exceeds frame-level tolerance")
    return CompositionResult(
        path=safe_output,
        media=output_descriptor,
        reused_single_clip=False,
    )


def inspect_clip(clip: ClipInput) -> MediaDescriptor:
    byte_size, digest = _hash_regular_file(clip.path)
    if digest != clip.sha256:
        raise ConcatError("segment sha256 does not match artifact descriptor")
    try:
        with av.open(str(clip.path)) as container:
            if not container.streams.video:
                raise ConcatError("segment has no video stream")
            stream = container.streams.video[0]
            rate = stream.average_rate
            if rate is None or rate <= 0:
                raise ConcatError("segment FPS is invalid")
            frames = list(container.decode(video=0))
            if not frames:
                raise ConcatError("segment has zero decodable frames")
            pixel_formats = {frame.format.name for frame in frames if frame.format is not None}
            if len(pixel_formats) != 1:
                raise ConcatError("segment pixel format changes between frames")
            fps = float(rate)
            frame_count = len(frames)
            return MediaDescriptor(
                path=clip.path.resolve(),
                profile=clip.profile,
                sha256=digest,
                byte_size=byte_size,
                duration_seconds=frame_count / fps,
                frame_count=frame_count,
                width=stream.width,
                height=stream.height,
                fps=fps,
                pixel_format=next(iter(pixel_formats)),
            )
    except ConcatError:
        raise
    except (av.error.FFmpegError, OSError, IndexError, ValueError) as error:
        raise ConcatError("segment cannot be decoded") from error


def concat_mp4s(inputs: tuple[Path, ...], output: Path) -> Path:
    """Backward-compatible multi-clip helper with the same strict media preflight."""
    if len(inputs) < 2:
        raise ConcatError("concatenation requires at least two segments")
    clips = tuple(
        ClipInput(
            path=path,
            profile=RenderProfile.PREVIEW,
            sha256=_hash_regular_file(path)[1],
        )
        for path in inputs
    )
    return compose_mp4s(clips, output, staging_root=output.parent).path


def _validate_compatible(descriptors: tuple[MediaDescriptor, ...]) -> None:
    reference = descriptors[0]
    for descriptor in descriptors[1:]:
        if descriptor.profile is not reference.profile:
            raise ConcatError("segment render profiles must match")
        if (descriptor.width, descriptor.height) != (reference.width, reference.height):
            raise ConcatError("segment dimensions must match")
        if abs(descriptor.fps - reference.fps) > 0.01:
            raise ConcatError("segment FPS must match")
        if descriptor.pixel_format != reference.pixel_format:
            raise ConcatError("segment pixel formats must match")


def _encode_hard_cuts(descriptors: tuple[MediaDescriptor, ...], output: Path) -> None:
    reference = descriptors[0]
    try:
        with av.open(str(output), mode="w") as destination:
            out_stream = destination.add_stream(
                "h264", rate=Fraction(reference.fps).limit_denominator(1_000)
            )
            out_stream.width = reference.width
            out_stream.height = reference.height
            out_stream.pix_fmt = reference.pixel_format
            output_frame_index = 0
            output_time_base = Fraction(1, 1) / Fraction(reference.fps).limit_denominator(1_000)
            for descriptor in descriptors:
                with av.open(str(descriptor.path)) as container:
                    for frame in container.decode(video=0):
                        frame.pts = output_frame_index
                        frame.time_base = output_time_base
                        output_frame_index += 1
                        packet = out_stream.encode(frame)
                        if packet:
                            destination.mux(packet)
            flushed = out_stream.encode(None)
            if flushed:
                destination.mux(flushed)
    except (av.error.FFmpegError, OSError, ValueError) as error:
        output.unlink(missing_ok=True)
        raise ConcatError("segment hard-cut encoding failed") from error


def _validate_staging_output(output: Path, staging_root: Path) -> Path:
    if staging_root.is_symlink():
        raise ConcatError("staging root must not be a symlink")
    try:
        resolved_root = staging_root.resolve(strict=True)
    except OSError as error:
        raise ConcatError("staging root does not exist") from error
    if not resolved_root.is_dir():
        raise ConcatError("staging root must be a directory")
    resolved_output = output.resolve(strict=False)
    if not resolved_output.parent.is_relative_to(resolved_root):
        raise ConcatError("composition output must stay inside staging root")
    if resolved_output.exists() or resolved_output.is_symlink():
        raise ConcatError("composition output already exists")
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    return resolved_output


def _hash_regular_file(path: Path) -> tuple[int, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ConcatError("segment cannot be opened safely") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0:
            raise ConcatError("segment must be a non-empty regular file")
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return metadata.st_size, digest.hexdigest()
    finally:
        os.close(descriptor)
