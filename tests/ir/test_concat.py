from pathlib import Path

import av
from manim_workbench_runner.rendering.concat import concat_mp4s


def _write_clip(path: Path, frames: int) -> None:
    output = av.open(str(path), mode="w")
    stream = output.add_stream("h264", rate=15)
    stream.width = 160
    stream.height = 90
    stream.pix_fmt = "yuv420p"
    blank = bytes(160 * 90)
    half = bytes(80 * 45)
    for _ in range(frames):
        frame = av.VideoFrame(width=160, height=90, format="yuv420p")
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
