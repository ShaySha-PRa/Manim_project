from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Protocol

from .models import FrameSample, MediaAnalysisError, MediaMetadata, validate_relative_media_path


class VideoReader(Protocol):
    def probe(self, media_root: Path, relative_media_path: Path) -> MediaMetadata: ...

    def read_frames(
        self, media_root: Path, relative_media_path: Path, indices: tuple[int, ...]
    ) -> tuple[FrameSample, ...]: ...


def _open_regular_media(media_root: Path, relative_media_path: Path) -> int:
    relative = validate_relative_media_path(media_root, relative_media_path)
    root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        root_fd = os.open(media_root, root_flags)
    except OSError:
        raise MediaAnalysisError("unsafe_media_path") from None
    descriptor = root_fd
    try:
        for position, component in enumerate(relative.parts):
            final = position == len(relative.parts) - 1
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            if not final:
                flags |= getattr(os, "O_DIRECTORY", 0)
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise MediaAnalysisError("unsafe_media_path")
        return descriptor
    except MediaAnalysisError:
        os.close(descriptor)
        raise
    except OSError:
        os.close(descriptor)
        raise MediaAnalysisError("media_open_failed") from None


class PyAVVideoReader:
    """PyAV adapter with descriptor-based opening; it never invokes a shell or network."""

    @staticmethod
    def _av():
        try:
            import av
        except ImportError:
            raise MediaAnalysisError("media_decoder_unavailable") from None
        return av

    def _container(self, media_root: Path, relative_media_path: Path):
        descriptor = _open_regular_media(media_root, relative_media_path)
        handle = os.fdopen(descriptor, "rb")
        try:
            container = self._av().open(handle, mode="r")
        except Exception:
            handle.close()
            raise MediaAnalysisError("malformed_media_metadata") from None
        return handle, container

    def probe(self, media_root: Path, relative_media_path: Path) -> MediaMetadata:
        handle, container = self._container(media_root, relative_media_path)
        try:
            stream = next((value for value in container.streams if value.type == "video"), None)
            if stream is None:
                raise MediaAnalysisError("malformed_media_metadata")
            fps = float(stream.average_rate or 0)
            if stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base)
            elif container.duration is not None:
                duration = float(container.duration / self._av().time_base)
            else:
                duration = 0.0
            return MediaMetadata(
                byte_size=os.fstat(handle.fileno()).st_size,
                width=int(stream.width),
                height=int(stream.height),
                frame_count=int(stream.frames or 0),
                duration_seconds=duration,
                fps=fps,
            )
        except MediaAnalysisError:
            raise
        except Exception:
            raise MediaAnalysisError("malformed_media_metadata") from None
        finally:
            container.close()
            handle.close()

    def read_frames(
        self, media_root: Path, relative_media_path: Path, indices: tuple[int, ...]
    ) -> tuple[FrameSample, ...]:
        handle, container = self._container(media_root, relative_media_path)
        try:
            stream = next((value for value in container.streams if value.type == "video"), None)
            if stream is None:
                raise MediaAnalysisError("frame_decode_failed")
            requested = set(indices)
            frames: list[FrameSample] = []
            for index, frame in enumerate(container.decode(stream)):
                if index not in requested:
                    continue
                rgb = frame.to_rgb()
                plane = rgb.planes[0]
                raw = bytes(plane)
                rows = [
                    raw[row * plane.line_size : row * plane.line_size + rgb.width * 3]
                    for row in range(rgb.height)
                ]
                timestamp = float(frame.time) if frame.time is not None else float(index)
                frames.append(FrameSample(index, timestamp, rgb.width, rgb.height, b"".join(rows)))
                if len(frames) == len(indices):
                    break
            if len(frames) != len(indices):
                raise MediaAnalysisError("frame_decode_failed")
            return tuple(frames)
        except MediaAnalysisError:
            raise
        except Exception:
            raise MediaAnalysisError("frame_decode_failed") from None
        finally:
            container.close()
            handle.close()
