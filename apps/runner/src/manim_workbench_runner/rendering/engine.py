from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

from .cache import build_cache_key, sha256_bytes
from .executor import CommandRunner, CommandTimedOut, SubprocessCommandRunner
from .models import (
    MANIM_IMAGE,
    MANIM_IMAGE_DIGEST,
    MANIM_VERSION,
    PROFILE_CONFIGS,
    RENDER_CONTRACT_VERSION,
    ArtifactInfo,
    RenderFailure,
    RenderFailureCode,
    RenderFailureResult,
    RenderRequest,
    RenderResult,
    RenderStage,
    RenderSuccess,
    VideoProbe,
)

PYAV_PROBE_SCRIPT = """
import av
import json

with av.open("/output/video.mp4") as container:
    stream = container.streams.video[0]
    fps = float(stream.average_rate or 0)
    if stream.duration is not None and stream.time_base is not None:
        duration = float(stream.duration * stream.time_base)
    elif container.duration is not None:
        duration = float(container.duration / av.time_base)
    else:
        duration = 0.0
    frames = int(stream.frames or 0)
    if frames <= 0:
        frames = sum(1 for _ in container.decode(stream))
    print(json.dumps({
        "streams": [{
            "width": stream.width,
            "height": stream.height,
            "avg_frame_rate": str(stream.average_rate or "0/1"),
            "nb_frames": frames,
        }],
        "format": {"duration": duration},
    }))
""".strip()

PYAV_THUMBNAIL_SCRIPT = """
import av

with av.open("/output/video.mp4") as container:
    stream = container.streams.video[0]
    if stream.duration is not None and stream.time_base is not None:
        target = float(stream.duration * stream.time_base) / 2
    elif container.duration is not None:
        target = float(container.duration / av.time_base) / 2
    else:
        target = 0.0
    selected = None
    for frame in container.decode(stream):
        selected = frame
        if frame.time is not None and frame.time >= target:
            break
    if selected is None:
        raise RuntimeError("video has no decodable frame")
    selected.to_image().save("/output/thumbnail.jpg", quality=85)
""".strip()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, relative_to: Path) -> ArtifactInfo:
    return ArtifactInfo(
        relative_path=path.relative_to(relative_to).as_posix(),
        byte_size=path.stat().st_size,
        sha256=_sha256_file(path),
    )


def validate_probe(value: VideoProbe | Path) -> VideoProbe | Path:
    if isinstance(value, Path):
        if not value.exists():
            raise RenderFailure(
                RenderFailureCode.MISSING_VIDEO, RenderStage.PROBE, "rendered video is missing"
            )
        if value.stat().st_size == 0:
            raise RenderFailure(
                RenderFailureCode.EMPTY_VIDEO, RenderStage.PROBE, "rendered video is empty"
            )
        return value
    if value.frame_count <= 0:
        raise RenderFailure(
            RenderFailureCode.ZERO_FRAMES, RenderStage.PROBE, "video has zero frames"
        )
    if not 0 < value.duration_seconds <= 300:
        raise RenderFailure(
            RenderFailureCode.INVALID_DURATION,
            RenderStage.PROBE,
            f"video duration {value.duration_seconds} is outside (0, 300] seconds",
        )
    if value.width <= 0 or value.height <= 0 or value.fps <= 0:
        raise RenderFailure(
            RenderFailureCode.FFPROBE_FAILED,
            RenderStage.PROBE,
            "video stream dimensions or frame rate are invalid",
        )
    return value


class RenderEngine:
    def __init__(
        self,
        *,
        project_root: Path | None = None,
        command_runner: CommandRunner | None = None,
        docker_command: Sequence[str] = ("docker",),
        utcnow: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.project_root = (project_root or Path.cwd()).resolve()
        self.command_runner = command_runner or SubprocessCommandRunner()
        self.docker_command = tuple(docker_command)
        self.utcnow = utcnow or (lambda: datetime.now(timezone.utc))
        self.monotonic = monotonic or time.perf_counter

    def render(
        self,
        request: RenderRequest,
        *,
        use_cache: bool = True,
        disable_manim_cache: bool = False,
    ) -> RenderResult:
        try:
            source = self._source_path(request)
            source_bytes = source.read_bytes()
        except RenderFailure as failure:
            return self._failure_result(request, failure, None)
        except OSError as exc:
            failure = RenderFailure(
                RenderFailureCode.ARTIFACT_IO_FAILED,
                RenderStage.PREPARE,
                f"could not read source: {exc}",
            )
            return self._failure_result(request, failure, None)

        cache_key = build_cache_key(request, source_bytes=source_bytes)
        artifact_root = self.project_root / request.artifact_root
        final_dir = artifact_root / cache_key
        cached = (
            self._cached_result(request, cache_key, final_dir, artifact_root)
            if use_cache
            else None
        )
        if cached is not None:
            return cached
        if final_dir.exists():
            try:
                shutil.rmtree(final_dir)
            except OSError as exc:
                failure = RenderFailure(
                    RenderFailureCode.ARTIFACT_IO_FAILED,
                    RenderStage.PREPARE,
                    f"could not replace invalid cache entry: {exc}",
                )
                return self._failure_result(request, failure, None)

        try:
            artifact_root.mkdir(parents=True, exist_ok=True)
            temp_dir = Path(tempfile.mkdtemp(prefix=f".{cache_key}-", dir=artifact_root))
        except OSError as exc:
            failure = RenderFailure(
                RenderFailureCode.ARTIFACT_IO_FAILED,
                RenderStage.PREPARE,
                f"could not create artifact directory: {exc}",
            )
            return self._failure_result(request, failure, None)

        log_lines: list[str] = []
        started_at = self.utcnow()
        started = self.monotonic()
        try:
            render_result = self._run_render(
                request, source, temp_dir, log_lines, disable_manim_cache=disable_manim_cache
            )
            video = self._collect_video(temp_dir)
            validate_probe(video)
            probe = self._run_probe(video, request, log_lines)
            validate_probe(probe)
            self._validate_profile(probe, request)
            thumbnail = self._run_thumbnail(video, temp_dir, request, probe, log_lines)
            if not thumbnail.exists() or thumbnail.stat().st_size == 0:
                raise RenderFailure(
                    RenderFailureCode.MISSING_THUMBNAIL,
                    RenderStage.THUMBNAIL,
                    "thumbnail was not produced",
                )
            render_log = temp_dir / "render.log"
            render_log.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
            finished_at = self.utcnow()
            wall_seconds = self.monotonic() - started
            metadata = self._metadata(
                request=request,
                cache_key=cache_key,
                source_bytes=source_bytes,
                started_at=started_at,
                finished_at=finished_at,
                wall_seconds=wall_seconds,
                render_seconds=render_result.duration_seconds,
                probe=probe,
                temp_dir=temp_dir,
            )
            (temp_dir / "metadata.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self._publish(temp_dir, final_dir, use_cache=use_cache)
            return self._success(request, cache_key, final_dir, artifact_root, cache_hit=False)
        except RenderFailure as failure:
            log_lines.append(
                f"FAILURE {failure.stage.value}/{failure.code.value}: {failure.message}"
            )
            log_path = self._preserve_failure_log(request, artifact_root, log_lines)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return self._failure_result(request, failure, log_path)
        except OSError as exc:
            log_lines.append(f"FAILURE publish/artifact_io_failed: {exc}")
            log_path = self._preserve_failure_log(request, artifact_root, log_lines)
            shutil.rmtree(temp_dir, ignore_errors=True)
            failure = RenderFailure(
                RenderFailureCode.ARTIFACT_IO_FAILED,
                RenderStage.PUBLISH,
                f"artifact operation failed: {exc}",
            )
            return self._failure_result(request, failure, log_path)

    def _source_path(self, request: RenderRequest) -> Path:
        source = (self.project_root / request.source_path).resolve()
        if not source.is_relative_to(self.project_root):
            raise RenderFailure(
                RenderFailureCode.INVALID_REQUEST,
                RenderStage.REQUEST,
                "source path leaves project root",
            )
        if not source.is_file():
            raise RenderFailure(
                RenderFailureCode.SOURCE_NOT_FOUND,
                RenderStage.REQUEST,
                "source file does not exist",
            )
        return source

    def _run(self, command: Sequence[str], timeout: int, stage: RenderStage, log: list[str]):
        log.append("COMMAND " + " ".join(command))
        try:
            result = self.command_runner.run(command, timeout_seconds=timeout)
        except FileNotFoundError as exc:
            raise RenderFailure(
                RenderFailureCode.DOCKER_UNAVAILABLE,
                stage,
                "docker executable is unavailable",
            ) from exc
        except CommandTimedOut as exc:
            log.append(exc.output)
            code = RenderFailureCode.RENDER_TIMEOUT if stage is RenderStage.RENDER else (
                RenderFailureCode.FFPROBE_FAILED
                if stage is RenderStage.PROBE
                else RenderFailureCode.FFMPEG_FAILED
            )
            raise RenderFailure(code, stage, "container command timed out") from exc
        log.append(result.output)
        return result

    def _base_docker(self, writable_dir: Path) -> list[str]:
        return [
            *self.docker_command,
            "run",
            "--rm",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--env",
            "HOME=/tmp",
            "--volume",
            f"{writable_dir}:/output",
        ]

    def _run_render(
        self,
        request: RenderRequest,
        source: Path,
        temp_dir: Path,
        log: list[str],
        *,
        disable_manim_cache: bool,
    ):
        profile = PROFILE_CONFIGS[request.profile]
        command = [
            *self._base_docker(temp_dir),
            "--volume",
            f"{source}:/input/scene.py:ro",
            "--workdir",
            "/input",
            "--entrypoint",
            "manim",
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
        ]
        if disable_manim_cache:
            command.append("--disable_caching")
        command.extend(["/input/scene.py", request.scene_class])
        result = self._run(command, profile.timeout_seconds, RenderStage.RENDER, log)
        if result.returncode != 0:
            code = (
                RenderFailureCode.CONTAINER_START_FAILED
                if result.returncode in {125, 126, 127}
                else RenderFailureCode.MANIM_RENDER_FAILED
            )
            raise RenderFailure(
                code,
                RenderStage.RENDER,
                f"Manim command exited with {result.returncode}",
                exit_code=result.returncode,
            )
        return result

    def _collect_video(self, temp_dir: Path) -> Path:
        videos = sorted((temp_dir / "media").rglob("video.mp4"))
        if not videos:
            raise RenderFailure(
                RenderFailureCode.MISSING_VIDEO, RenderStage.RENDER, "Manim produced no MP4"
            )
        video = temp_dir / "video.mp4"
        videos[-1].replace(video)
        shutil.rmtree(temp_dir / "media", ignore_errors=True)
        return video

    def _run_probe(self, video: Path, request: RenderRequest, log: list[str]) -> VideoProbe:
        command = [
            *self._base_docker(video.parent),
            "--entrypoint",
            "python",
            MANIM_IMAGE,
            "-c",
            PYAV_PROBE_SCRIPT,
        ]
        result = self._run(command, 30, RenderStage.PROBE, log)
        if result.returncode != 0:
            raise RenderFailure(
                RenderFailureCode.FFPROBE_FAILED,
                RenderStage.PROBE,
                f"ffprobe exited with {result.returncode}",
                exit_code=result.returncode,
            )
        try:
            payload = json.loads(result.output)
            stream = payload["streams"][0]
            duration = float(payload["format"]["duration"])
            fps = float(Fraction(stream["avg_frame_rate"]))
            frames = int(stream.get("nb_frames") or round(duration * fps))
            return VideoProbe(duration, frames, int(stream["width"]), int(stream["height"]), fps)
        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            ZeroDivisionError,
            json.JSONDecodeError,
        ) as exc:
            raise RenderFailure(
                RenderFailureCode.FFPROBE_FAILED,
                RenderStage.PROBE,
                "ffprobe returned invalid JSON or stream fields",
            ) from exc

    def _run_thumbnail(
        self,
        video: Path,
        temp_dir: Path,
        request: RenderRequest,
        probe: VideoProbe,
        log: list[str],
    ) -> Path:
        command = [
            *self._base_docker(video.parent),
            "--entrypoint",
            "python",
            MANIM_IMAGE,
            "-c",
            PYAV_THUMBNAIL_SCRIPT,
        ]
        result = self._run(command, 30, RenderStage.THUMBNAIL, log)
        if result.returncode != 0:
            raise RenderFailure(
                RenderFailureCode.FFMPEG_FAILED,
                RenderStage.THUMBNAIL,
                f"ffmpeg exited with {result.returncode}",
                exit_code=result.returncode,
            )
        return temp_dir / "thumbnail.jpg"

    def _validate_profile(self, probe: VideoProbe, request: RenderRequest) -> None:
        profile = PROFILE_CONFIGS[request.profile]
        if (probe.width, probe.height) != (profile.width, profile.height):
            raise RenderFailure(
                RenderFailureCode.FFPROBE_FAILED,
                RenderStage.PROBE,
                "video resolution does not match the requested profile",
            )
        if abs(probe.fps - profile.frame_rate) > 0.01:
            raise RenderFailure(
                RenderFailureCode.FFPROBE_FAILED,
                RenderStage.PROBE,
                "video frame rate does not match the requested profile",
            )

    def _metadata(
        self,
        *,
        request: RenderRequest,
        cache_key: str,
        source_bytes: bytes,
        started_at: datetime,
        finished_at: datetime,
        wall_seconds: float,
        render_seconds: float,
        probe: VideoProbe,
        temp_dir: Path,
    ) -> dict[str, object]:
        artifact_data = {}
        for name, filename in {
            "video": "video.mp4",
            "thumbnail": "thumbnail.jpg",
            "render_log": "render.log",
        }.items():
            path = temp_dir / filename
            artifact_data[name] = {"byte_size": path.stat().st_size, "sha256": _sha256_file(path)}
        return {
            "contract_version": RENDER_CONTRACT_VERSION,
            "scene_id": request.scene_id,
            "scene_class": request.scene_class,
            "source_path": request.source_path.as_posix(),
            "source_sha256": sha256_bytes(source_bytes),
            "profile": request.profile.value,
            "engine": "manimce",
            "engine_version": MANIM_VERSION,
            "image_digest": MANIM_IMAGE_DIGEST,
            "cache_key": cache_key,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "wall_seconds": round(wall_seconds, 6),
            "render_seconds": round(render_seconds, 6),
            "video": {
                "duration_seconds": probe.duration_seconds,
                "frame_count": probe.frame_count,
                "width": probe.width,
                "height": probe.height,
                "fps": probe.fps,
            },
            "artifacts": artifact_data,
        }

    def _publish(self, temp_dir: Path, final_dir: Path, *, use_cache: bool) -> None:
        if final_dir.exists():
            if use_cache:
                shutil.rmtree(temp_dir)
                return
            shutil.rmtree(final_dir)
        temp_dir.replace(final_dir)

    def _cached_result(
        self,
        request: RenderRequest,
        cache_key: str,
        final_dir: Path,
        artifact_root: Path,
    ) -> RenderSuccess | None:
        required = ["video.mp4", "thumbnail.jpg", "render.log", "metadata.json"]
        if not final_dir.is_dir() or any(not (final_dir / name).is_file() for name in required):
            return None
        if any((final_dir / name).stat().st_size == 0 for name in required):
            return None
        try:
            result = self._success(request, cache_key, final_dir, artifact_root, cache_hit=True)
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if result.metadata.get("cache_key") != cache_key:
            return None
        return result

    def _success(
        self,
        request: RenderRequest,
        cache_key: str,
        final_dir: Path,
        artifact_root: Path,
        *,
        cache_hit: bool,
    ) -> RenderSuccess:
        files = {
            "video": final_dir / "video.mp4",
            "thumbnail": final_dir / "thumbnail.jpg",
            "render_log": final_dir / "render.log",
            "metadata": final_dir / "metadata.json",
        }
        metadata = json.loads(files["metadata"].read_text(encoding="utf-8"))
        artifacts = {name: _artifact(path, artifact_root) for name, path in files.items()}
        return RenderSuccess(
            True,
            request.scene_id,
            request.profile,
            cache_key,
            cache_hit,
            artifacts,
            metadata,
        )

    def _preserve_failure_log(
        self, request: RenderRequest, artifact_root: Path, lines: list[str]
    ) -> Path | None:
        try:
            failures = artifact_root / "failures"
            failures.mkdir(parents=True, exist_ok=True)
            path = failures / f"{request.scene_id}-{uuid4().hex}.log"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return path
        except OSError:
            return None

    def _failure_result(
        self, request: RenderRequest, failure: RenderFailure, log_path: Path | None
    ) -> RenderFailureResult:
        relative = None
        if log_path is not None:
            try:
                relative = log_path.relative_to(self.project_root).as_posix()
            except ValueError:
                relative = log_path.as_posix()
        return RenderFailureResult(
            False,
            request.scene_id,
            request.profile,
            failure.code,
            failure.stage,
            failure.message,
            failure.exit_code,
            relative,
        )
