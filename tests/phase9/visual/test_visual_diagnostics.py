from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from traceback import format_exception

import pytest


@dataclass(frozen=True, slots=True)
class FakeFrame:
    index: int
    timestamp_seconds: float
    width: int
    height: int
    pixels: bytes


@dataclass(frozen=True, slots=True)
class FakeMetadata:
    byte_size: int = 1_024
    width: int = 40
    height: int = 30
    frame_count: int = 12
    duration_seconds: float = 12.0
    fps: float = 1.0


class FakeReader:
    def __init__(self, metadata: FakeMetadata, frames: tuple[FakeFrame, ...]) -> None:
        self.metadata = metadata
        self.frames = frames
        self.requested_indices: tuple[int, ...] = ()

    def probe(self, media_root: Path, relative_media_path: Path):
        del media_root, relative_media_path
        return self.metadata

    def read_frames(self, media_root: Path, relative_media_path: Path, indices: tuple[int, ...]):
        del media_root, relative_media_path
        self.requested_indices = indices
        by_index = {frame.index: frame for frame in self.frames}
        return tuple(by_index[index] for index in indices)


class ExplodingReader(FakeReader):
    def read_frames(self, media_root: Path, relative_media_path: Path, indices: tuple[int, ...]):
        del media_root, relative_media_path, indices
        raise RuntimeError("/host/secret/video.mp4 decoder exploded")


def _solid_frame(index: int, timestamp: float, rgb: tuple[int, int, int]) -> FakeFrame:
    width, height = 40, 30
    return FakeFrame(index, timestamp, width, height, bytes(rgb) * (width * height))


def _paint(
    frame: FakeFrame,
    *,
    left: int,
    top: int,
    right: int,
    bottom: int,
    rgb: tuple[int, int, int],
) -> FakeFrame:
    pixels = bytearray(frame.pixels)
    for y in range(top, bottom):
        for x in range(left, right):
            offset = (y * frame.width + x) * 3
            pixels[offset : offset + 3] = bytes(rgb)
    return FakeFrame(frame.index, frame.timestamp_seconds, frame.width, frame.height, bytes(pixels))


def _tofu_frame(index: int, timestamp: float) -> FakeFrame:
    frame = _solid_frame(index, timestamp, (0, 0, 0))
    for left in (4, 13, 22, 31):
        frame = _paint(frame, left=left, top=7, right=left + 6, bottom=8, rgb=(255, 255, 255))
        frame = _paint(frame, left=left, top=14, right=left + 6, bottom=15, rgb=(255, 255, 255))
        frame = _paint(frame, left=left, top=7, right=left + 1, bottom=15, rgb=(255, 255, 255))
        frame = _paint(frame, left=left + 5, top=7, right=left + 6, bottom=15, rgb=(255, 255, 255))
    return frame


def _analyzer(reader: FakeReader, **overrides):
    from manim_workbench_runner.quality.visual import VisualDiagnosticAnalyzer, VisualLimits

    return VisualDiagnosticAnalyzer(
        reader=reader,
        limits=VisualLimits(sample_count=4, max_frame_count=100, **overrides),
    )


def test_sampling_is_even_deterministic_and_bounded() -> None:
    from manim_workbench_runner.quality.visual import deterministic_frame_indices

    assert deterministic_frame_indices(frame_count=12, sample_count=4) == (0, 3, 7, 11)
    assert deterministic_frame_indices(frame_count=1, sample_count=8) == (0,)
    with pytest.raises(ValueError, match="sample_count"):
        deterministic_frame_indices(frame_count=1, sample_count=0)


def test_analyzer_reports_blank_static_edge_tofu_and_missing_expected_object(
    tmp_path: Path,
) -> None:
    from manim_workbench_runner.quality.visual import ExpectedObjectProxy

    blank = _solid_frame(0, 0, (0, 0, 0))
    edge = _paint(blank, left=0, top=5, right=8, bottom=18, rgb=(255, 255, 255))
    tofu = _tofu_frame(7, 7)
    reader = FakeReader(
        FakeMetadata(),
        tuple(
            FakeFrame(index, float(index), frame.width, frame.height, frame.pixels)
            for index, frame in enumerate(
                (blank, blank, edge, edge, edge, edge, tofu, tofu, tofu, tofu, tofu, tofu)
            )
        ),
    )

    result = _analyzer(reader, static_threshold_seconds=2).analyze(
        media_root=tmp_path,
        relative_media_path=Path("job/video.mp4"),
        target_duration_seconds=12,
        expected_objects=(ExpectedObjectProxy("parabola", (0, 255, 0), 5),),
    )

    assert reader.requested_indices == (0, 3, 7, 11)
    codes = {item.code for item in result.diagnostics}
    assert {
        "blank_frame",
        "long_static_segment",
        "object_out_of_bounds",
        "cjk_glyph_missing",
        "object_missing",
    } <= codes
    assert all(not item.evidence_ref.startswith("/") for item in result.diagnostics)
    assert all("tmp" not in item.summary.lower() for item in result.diagnostics)


def test_obvious_overlap_and_small_text_proxies_are_detected(tmp_path: Path) -> None:
    base = _solid_frame(0, 0, (0, 0, 0))
    overlap = _paint(base, left=10, top=8, right=30, bottom=22, rgb=(255, 0, 0))
    overlap = _paint(overlap, left=16, top=10, right=24, bottom=20, rgb=(0, 255, 0))
    small = overlap
    for left in range(1, 36, 3):
        small = _paint(small, left=left, top=2, right=left + 1, bottom=4, rgb=(255, 255, 255))
    reader = FakeReader(
        FakeMetadata(),
        tuple(FakeFrame(index, float(index), 40, 30, small.pixels) for index in range(12)),
    )

    result = _analyzer(reader, overlap_cell_size=8, min_small_text_components=3).analyze(
        media_root=tmp_path,
        relative_media_path=Path("job/video.mp4"),
        target_duration_seconds=12,
    )

    assert {"object_overlap", "text_too_small"} <= {item.code for item in result.diagnostics}


def test_malformed_metadata_and_reader_failure_are_closed_and_redacted(tmp_path: Path) -> None:
    from manim_workbench_runner.quality.visual import MediaAnalysisError

    malformed = FakeReader(FakeMetadata(width=0), ())
    with pytest.raises(MediaAnalysisError) as malformed_error:
        _analyzer(malformed).analyze(
            media_root=tmp_path,
            relative_media_path=Path("job/video.mp4"),
            target_duration_seconds=12,
        )
    assert malformed_error.value.code == "malformed_media_metadata"
    assert str(tmp_path) not in str(malformed_error.value)

    failure = ExplodingReader(FakeMetadata(), ())
    with pytest.raises(MediaAnalysisError) as failure_error:
        _analyzer(failure).analyze(
            media_root=tmp_path,
            relative_media_path=Path("job/video.mp4"),
            target_duration_seconds=12,
        )
    assert failure_error.value.code == "frame_decode_failed"
    assert "/host/secret" not in str(failure_error.value)
    assert "/host/secret" not in "".join(format_exception(failure_error.value))


@pytest.mark.parametrize(
    ("metadata", "limits", "expected_code"),
    [
        (FakeMetadata(byte_size=1_025), {"max_media_bytes": 1_024}, "media_size_limit"),
        (FakeMetadata(frame_count=101), {}, "frame_count_limit"),
        (FakeMetadata(duration_seconds=0), {}, "malformed_media_metadata"),
        (FakeMetadata(width=100, height=100), {"max_pixels_per_frame": 1_000}, "dimension_limit"),
    ],
)
def test_resource_limits_fail_before_frame_decoding(
    tmp_path: Path, metadata: FakeMetadata, limits: dict[str, int], expected_code: str
) -> None:
    from manim_workbench_runner.quality.visual import MediaAnalysisError

    reader = FakeReader(metadata, ())
    with pytest.raises(MediaAnalysisError) as error:
        _analyzer(reader, **limits).analyze(
            media_root=tmp_path,
            relative_media_path=Path("job/video.mp4"),
            target_duration_seconds=12,
        )
    assert error.value.code == expected_code
    assert reader.requested_indices == ()


def test_relative_media_path_rejects_traversal_and_symlink_without_absolute_path_leakage(
    tmp_path: Path,
) -> None:
    from manim_workbench_runner.quality.visual import (
        MediaAnalysisError,
        PyAVVideoReader,
        validate_relative_media_path,
    )

    with pytest.raises(MediaAnalysisError) as traversal:
        validate_relative_media_path(tmp_path, Path("../outside.mp4"))
    assert traversal.value.code == "unsafe_media_path"
    assert str(tmp_path) not in str(traversal.value)

    target = tmp_path / "target.mp4"
    target.write_bytes(b"video")
    link = tmp_path / "link.mp4"
    link.symlink_to(target)
    with pytest.raises(MediaAnalysisError) as symlink:
        validate_relative_media_path(tmp_path, Path("link.mp4"))
    assert symlink.value.code == "unsafe_media_path"
    assert str(target) not in str(symlink.value)

    with pytest.raises(MediaAnalysisError) as reader_symlink:
        PyAVVideoReader().probe(tmp_path, Path("link.mp4"))
    assert reader_symlink.value.code == "unsafe_media_path"


def test_time_budget_fails_after_bounded_reader_returns(tmp_path: Path) -> None:
    from manim_workbench_runner.quality.visual import (
        MediaAnalysisError,
        VisualDiagnosticAnalyzer,
        VisualLimits,
    )

    frame = _solid_frame(0, 0, (0, 0, 0))
    reader = FakeReader(
        FakeMetadata(),
        tuple(FakeFrame(index, float(index), 40, 30, frame.pixels) for index in range(12)),
    )
    ticks = iter((0.0, 0.0, 2.0))
    analyzer = VisualDiagnosticAnalyzer(
        reader=reader,
        limits=VisualLimits(sample_count=4, max_frame_count=100, max_analysis_seconds=1),
        monotonic=lambda: next(ticks),
    )

    with pytest.raises(MediaAnalysisError) as error:
        analyzer.analyze(
            media_root=tmp_path,
            relative_media_path=Path("job/video.mp4"),
            target_duration_seconds=12,
        )
    assert error.value.code == "analysis_time_limit"


def test_results_are_repeatable_and_only_contain_redacted_relative_evidence(tmp_path: Path) -> None:
    from manim_workbench_runner.quality.visual import ExpectedObjectProxy

    frame = _solid_frame(0, 0, (0, 0, 0))
    frames = tuple(FakeFrame(index, float(index), 40, 30, frame.pixels) for index in range(12))
    first = _analyzer(FakeReader(FakeMetadata(), frames)).analyze(
        media_root=tmp_path,
        relative_media_path=Path("artifact/video.mp4"),
        target_duration_seconds=12,
        expected_objects=(ExpectedObjectProxy("formula", (255, 255, 255), 1),),
    )
    second = _analyzer(FakeReader(FakeMetadata(), frames)).analyze(
        media_root=tmp_path,
        relative_media_path=Path("artifact/video.mp4"),
        target_duration_seconds=12,
        expected_objects=(ExpectedObjectProxy("formula", (255, 255, 255), 1),),
    )

    assert first == second
    assert first.signature == second.signature
    assert str(tmp_path) not in repr(first)
    assert all(item.evidence_ref.startswith("visual/") for item in first.diagnostics)
