"""Concatenate independently rendered MP4 segments into one teaching video."""

from __future__ import annotations

from pathlib import Path

import av


class ConcatError(ValueError):
    """Raised when segment videos cannot be concatenated."""


def concat_mp4s(inputs: tuple[Path, ...], output: Path) -> Path:
    if len(inputs) < 2:
        raise ConcatError("concatenation requires at least two segments")
    output.parent.mkdir(parents=True, exist_ok=True)
    first = av.open(str(inputs[0]))
    try:
        source_stream = first.streams.video[0]
        destination = av.open(str(output), mode="w")
        try:
            out_stream = destination.add_stream("h264", rate=source_stream.average_rate or 15)
            out_stream.width = source_stream.width
            out_stream.height = source_stream.height
            out_stream.pix_fmt = "yuv420p"
            for path in inputs:
                container = first if path == inputs[0] else av.open(str(path))
                try:
                    stream = container.streams.video[0]
                    if stream.width != out_stream.width or stream.height != out_stream.height:
                        raise ConcatError("segment dimensions must match")
                    for frame in container.decode(video=0):
                        frame.pts = None
                        packet = out_stream.encode(frame)
                        if packet:
                            destination.mux(packet)
                finally:
                    if container is not first:
                        container.close()
            flushed = out_stream.encode(None)
            if flushed:
                destination.mux(flushed)
        finally:
            destination.close()
    finally:
        first.close()
    return output
