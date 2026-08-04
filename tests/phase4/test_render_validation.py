from pathlib import Path

import pytest
from manim_workbench_runner.rendering import (
    RenderFailure,
    RenderFailureCode,
    VideoProbe,
    validate_probe,
)


def test_probe_rejects_zero_frames() -> None:
    probe = VideoProbe(duration_seconds=4.0, frame_count=0, width=854, height=480, fps=15.0)
    with pytest.raises(RenderFailure) as raised:
        validate_probe(probe)
    assert raised.value.code is RenderFailureCode.ZERO_FRAMES


@pytest.mark.parametrize("duration", [0.0, -1.0, 301.0])
def test_probe_rejects_invalid_duration(duration: float) -> None:
    probe = VideoProbe(duration_seconds=duration, frame_count=1, width=854, height=480, fps=15.0)
    with pytest.raises(RenderFailure) as raised:
        validate_probe(probe)
    assert raised.value.code is RenderFailureCode.INVALID_DURATION


def test_probe_rejects_empty_video_before_ffprobe(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.touch()
    with pytest.raises(RenderFailure) as raised:
        validate_probe(video)
    assert raised.value.code is RenderFailureCode.EMPTY_VIDEO
