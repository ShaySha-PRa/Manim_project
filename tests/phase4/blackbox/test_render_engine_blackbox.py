"""Black-box acceptance tests for the Phase 4 rendering contract.

These tests deliberately use no Docker daemon. The injected executor mimics
the external command boundary while assertions observe published artifacts and
stable public result fields.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from manim_workbench_runner.rendering import (
    CommandResult,
    CommandTimedOut,
    RenderEngine,
    RenderFailureCode,
    RenderFailureResult,
    RenderProfile,
    RenderRequest,
    RenderSuccess,
)


class FakeExecutor:
    """Filesystem-backed fake for Docker, Manim, ffprobe and ffmpeg commands."""

    def __init__(self, mode: str = "success") -> None:
        self.mode = mode
        self.calls: list[list[str]] = []

    def run(self, command: Sequence[str], *, timeout_seconds: int) -> CommandResult:
        del timeout_seconds
        values = [str(item) for item in command]
        self.calls.append(values)
        entrypoint = self._option(values, "--entrypoint")
        python_script = self._option(values, "-c")
        if self.mode == "docker_unavailable":
            raise FileNotFoundError("docker is unavailable")
        if self.mode == "timeout" and entrypoint == "manim":
            raise CommandTimedOut(values, "renderer timed out")
        if entrypoint == "python" and python_script is not None:
            if "thumbnail.jpg" in python_script:
                return self._thumbnail_python(values)
            if '"streams"' in python_script and "json.dumps" in python_script:
                return self._probe_python(values)
            raise AssertionError("unrecognised PyAV command intent")
        if entrypoint == "manim":
            return self._manim(values)
        return self._result(values, 0, "docker probe ok")

    def _manim(self, command: list[str]) -> CommandResult:
        if self.mode == "container_start_failed":
            return self._result(command, 125, "container start failed")
        if self.mode == "manim_render_failed":
            return self._result(command, 1, "manim failed")
        if self.mode == "missing_video":
            return self._result(command, 0, "no video emitted")

        media_dir = self._host_path(self._option(command, "--media_dir"), command)
        output_name = self._option(command, "--output_file")
        assert media_dir is not None and output_name is not None
        video = media_dir / "videos" / "fake" / f"{Path(output_name).stem}.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        if self.mode == "empty_video":
            video.touch()
        else:
            video.write_bytes(b"not-a-real-mp4-but-non-empty")
        return self._result(command, 0, "manim completed")

    def _probe_python(self, command: list[str]) -> CommandResult:
        if self.mode == "ffprobe_failed":
            return self._result(command, 1, "ffprobe failed")
        frame_count = 0 if self.mode == "zero_frames" else 60
        duration = 0.0 if self.mode == "invalid_duration" else 4.0
        payload = {
            "format": {"duration": str(duration)},
            "streams": [
                {
                    "codec_type": "video",
                    "width": 854,
                    "height": 480,
                    "avg_frame_rate": "15/1",
                    "nb_frames": str(frame_count),
                }
            ],
        }
        return self._result(command, 0, json.dumps(payload))

    def _thumbnail_python(self, command: list[str]) -> CommandResult:
        if self.mode == "ffmpeg_failed":
            return self._result(command, 1, "ffmpeg failed")
        if self.mode != "missing_thumbnail":
            thumbnail = self._host_path("/output/thumbnail.jpg", command)
            assert thumbnail is not None
            thumbnail.parent.mkdir(parents=True, exist_ok=True)
            thumbnail.write_bytes(b"jpeg")
        return self._result(command, 0, "thumbnail complete")

    @staticmethod
    def _result(command: Sequence[str], returncode: int, output: str) -> CommandResult:
        return CommandResult(tuple(command), returncode, output, duration_seconds=0.25)

    @staticmethod
    def _option(command: list[str], name: str) -> str | None:
        try:
            return command[command.index(name) + 1]
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _host_path(value: str | None, command: list[str]) -> Path | None:
        if value is None:
            return None
        candidate = Path(value)
        if candidate.exists() or not candidate.is_absolute():
            return candidate
        for flag in ("--volume", "-v"):
            for index, item in enumerate(command[:-1]):
                if item != flag:
                    continue
                host, separator, container = command[index + 1].partition(":")
                if separator and value.startswith(container):
                    return Path(host) / value.removeprefix(container).lstrip("/")
        return candidate


@pytest.fixture
def render_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RenderRequest:
    monkeypatch.chdir(tmp_path)
    source = Path("reference_scenes/formula/quadratic_formula.py")
    source.parent.mkdir(parents=True)
    source.write_text("class QuadraticFormulaDerivation(Scene):\n    pass\n", encoding="utf-8")
    return RenderRequest(
        scene_id="quadratic_formula",
        scene_class="QuadraticFormulaDerivation",
        source_path=source,
        profile=RenderProfile.PREVIEW,
        artifact_root=Path("artifacts"),
    )

def assert_success_is_published(
    result: object, request: RenderRequest, project_root: Path
) -> Path:
    assert isinstance(result, RenderSuccess)
    cache_dir = project_root / request.artifact_root / result.cache_key
    assert cache_dir.is_dir()
    for name in ("video.mp4", "thumbnail.jpg", "render.log", "metadata.json"):
        assert (cache_dir / name).is_file(), f"missing published {name}"
    artifact_paths = [artifact.relative_path for artifact in result.artifacts.values()]
    for name in ("video.mp4", "thumbnail.jpg", "render.log", "metadata.json"):
        assert any(path.endswith(name) for path in artifact_paths)
    return cache_dir


def test_success_is_published_as_one_complete_cache_entry(render_request: RenderRequest) -> None:
    project_root = Path.cwd()
    engine = RenderEngine(project_root=project_root, command_runner=FakeExecutor())
    result = engine.render(render_request)

    cache_dir = assert_success_is_published(result, render_request, project_root)
    artifact_root = project_root / render_request.artifact_root
    assert list(artifact_root.iterdir()) == [cache_dir]
    assert not any(path.name.startswith(".") for path in artifact_root.iterdir())


def test_second_identical_request_is_a_cache_hit_without_reinvoking_manim(
    render_request: RenderRequest,
) -> None:
    project_root = Path.cwd()
    first_executor = FakeExecutor()
    engine = RenderEngine(project_root=project_root, command_runner=first_executor)
    first = engine.render(render_request)
    assert_success_is_published(first, render_request, project_root)

    second_executor = FakeExecutor(mode="manim_render_failed")
    engine = RenderEngine(project_root=project_root, command_runner=second_executor)
    cached = engine.render(render_request)

    assert_success_is_published(cached, render_request, project_root)
    assert cached.cache_hit is True
    assert not any("manim" in " ".join(command) for command in second_executor.calls)


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("docker_unavailable", RenderFailureCode.DOCKER_UNAVAILABLE),
        ("container_start_failed", RenderFailureCode.CONTAINER_START_FAILED),
        ("timeout", RenderFailureCode.RENDER_TIMEOUT),
        ("manim_render_failed", RenderFailureCode.MANIM_RENDER_FAILED),
        ("missing_video", RenderFailureCode.MISSING_VIDEO),
        ("empty_video", RenderFailureCode.EMPTY_VIDEO),
        ("ffprobe_failed", RenderFailureCode.FFPROBE_FAILED),
        ("zero_frames", RenderFailureCode.ZERO_FRAMES),
        ("invalid_duration", RenderFailureCode.INVALID_DURATION),
        ("ffmpeg_failed", RenderFailureCode.FFMPEG_FAILED),
        ("missing_thumbnail", RenderFailureCode.MISSING_THUMBNAIL),
    ],
)
def test_injected_external_failure_is_classified_and_never_published(
    render_request: RenderRequest, mode: str, code: RenderFailureCode
) -> None:
    project_root = Path.cwd()
    engine = RenderEngine(project_root=project_root, command_runner=FakeExecutor(mode))
    result = engine.render(render_request)

    assert isinstance(result, RenderFailureResult)
    assert result.code is code
    assert result.log_relative_path is not None
    log_path = project_root / result.log_relative_path
    assert log_path.is_file()
    assert log_path.read_text(encoding="utf-8")
    assert not list((project_root / render_request.artifact_root).rglob("metadata.json"))
