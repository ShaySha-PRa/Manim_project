from hashlib import sha256
from pathlib import Path

import av
import pytest
from manim_workbench_contracts import RenderProfile
from manim_workbench_runner.rendering.concat import (
    ClipInput,
    ConcatError,
    compose_mp4s,
    concat_mp4s,
)


def _write_clip(
    path: Path,
    frames: int,
    *,
    width: int = 160,
    height: int = 90,
    rate: int = 15,
) -> None:
    output = av.open(str(path), mode="w")
    stream = output.add_stream("h264", rate=rate)
    stream.width = width
    stream.height = height
    stream.pix_fmt = "yuv420p"
    blank = bytes(width * height)
    half = bytes((width // 2) * (height // 2))
    for _ in range(frames):
        frame = av.VideoFrame(width=width, height=height, format="yuv420p")
        frame.planes[0].update(blank)
        frame.planes[1].update(half)
        frame.planes[2].update(half)
        packet = stream.encode(frame)
        if packet:
            output.mux(packet)
    flushed = stream.encode(None)
    if flushed:
        output.mux(flushed)
    output.close()


def test_concat_mp4s_joins_equal_segments(tmp_path: Path) -> None:
    first = tmp_path / "a.mp4"
    second = tmp_path / "b.mp4"
    _write_clip(first, 8)
    _write_clip(second, 8)
    joined = concat_mp4s((first, second), tmp_path / "out.mp4")
    with av.open(str(joined)) as container:
        count = sum(1 for _ in container.decode(video=0))
    assert count >= 14


def _clip(path: Path, profile: RenderProfile = RenderProfile.PREVIEW) -> ClipInput:
    return ClipInput(
        path=path,
        profile=profile,
        sha256=sha256(path.read_bytes()).hexdigest(),
    )


def test_single_clip_is_validated_and_reused_without_copy(tmp_path: Path) -> None:
    source = tmp_path / "single.mp4"
    _write_clip(source, 8)
    output = tmp_path / "unused.mp4"

    result = compose_mp4s((_clip(source),), output, staging_root=tmp_path)

    assert result.reused_single_clip is True
    assert result.path == source.resolve()
    assert result.media.frame_count == 8
    assert not output.exists()


def test_compose_rejects_hash_profile_dimension_and_fps_mismatch(tmp_path: Path) -> None:
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    different_size = tmp_path / "size.mp4"
    different_fps = tmp_path / "fps.mp4"
    _write_clip(first, 8)
    _write_clip(second, 8)
    _write_clip(different_size, 8, width=320, height=180)
    _write_clip(different_fps, 8, rate=30)

    with pytest.raises(ConcatError, match="sha256"):
        compose_mp4s(
            (ClipInput(first, RenderProfile.PREVIEW, "0" * 64),),
            tmp_path / "hash.mp4",
            staging_root=tmp_path,
        )
    with pytest.raises(ConcatError, match="profiles"):
        compose_mp4s(
            (_clip(first), _clip(second, RenderProfile.FINAL)),
            tmp_path / "profile.mp4",
            staging_root=tmp_path,
        )
    with pytest.raises(ConcatError, match="dimensions"):
        compose_mp4s(
            (_clip(first), _clip(different_size)),
            tmp_path / "size-out.mp4",
            staging_root=tmp_path,
        )
    with pytest.raises(ConcatError, match="FPS"):
        compose_mp4s(
            (_clip(first), _clip(different_fps)),
            tmp_path / "fps-out.mp4",
            staging_root=tmp_path,
        )


def test_compose_rejects_zero_frame_and_output_outside_staging(tmp_path: Path) -> None:
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"not-a-decodable-mp4")
    with pytest.raises(ConcatError, match="cannot be decoded"):
        compose_mp4s((_clip(empty),), tmp_path / "empty-out.mp4", staging_root=tmp_path)

    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    _write_clip(first, 4)
    _write_clip(second, 4)
    with pytest.raises(ConcatError, match="inside staging root"):
        compose_mp4s(
            (_clip(first), _clip(second)),
            tmp_path.parent / "escaped.mp4",
            staging_root=tmp_path,
        )


def test_composed_media_preserves_frame_level_total_duration(tmp_path: Path) -> None:
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    _write_clip(first, 8)
    _write_clip(second, 12)

    result = compose_mp4s(
        (_clip(first), _clip(second)),
        tmp_path / "joined.mp4",
        staging_root=tmp_path,
    )

    assert result.reused_single_clip is False
    assert abs(result.media.frame_count - 20) <= 2
    assert abs(result.media.duration_seconds - (20 / 15)) <= 2 / 15
    assert result.media.sha256 == sha256(result.path.read_bytes()).hexdigest()
