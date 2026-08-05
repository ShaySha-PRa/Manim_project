from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .models import (
    ExpectedObjectProxy,
    FrameSample,
    MediaAnalysisError,
    MediaMetadata,
    VisualAnalysisResult,
    VisualDiagnostic,
    VisualEvidence,
    VisualLimits,
    validate_relative_media_path,
)
from .reader import PyAVVideoReader, VideoReader


def deterministic_frame_indices(*, frame_count: int, sample_count: int) -> tuple[int, ...]:
    if frame_count < 1:
        raise ValueError("frame_count must be positive")
    if sample_count < 1:
        raise ValueError("sample_count must be positive")
    count = min(frame_count, sample_count)
    if count == 1:
        return (0,)
    return tuple((index * (frame_count - 1)) // (count - 1) for index in range(count))


@dataclass(frozen=True, slots=True)
class _FrameFacts:
    frame: FrameSample
    active: tuple[bool, ...]
    active_count: int
    edge_count: int
    color_boxes: tuple[tuple[tuple[int, int, int], tuple[int, int, int, int], int], ...]
    fingerprint: bytes
    small_component_count: int
    tofu_component_count: int


class VisualDiagnosticAnalyzer:
    """Pure-rule visual analysis with an injectable reader for safe parent integration."""

    def __init__(
        self,
        *,
        reader: VideoReader | None = None,
        limits: VisualLimits | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.reader = reader or PyAVVideoReader()
        self.limits = limits or VisualLimits()
        self.monotonic = monotonic or time.monotonic

    def analyze(
        self,
        *,
        media_root: Path,
        relative_media_path: Path,
        target_duration_seconds: float,
        expected_objects: tuple[ExpectedObjectProxy, ...] = (),
    ) -> VisualAnalysisResult:
        if not 0 < target_duration_seconds <= self.limits.max_duration_seconds:
            raise MediaAnalysisError("invalid_target_duration")
        relative = validate_relative_media_path(media_root, relative_media_path)
        started = self.monotonic()
        try:
            metadata = self.reader.probe(media_root, relative)
        except MediaAnalysisError:
            raise
        except Exception:
            raise MediaAnalysisError("malformed_media_metadata") from None
        self._check_metadata(metadata)
        self._check_budget(started)

        indices = deterministic_frame_indices(
            frame_count=metadata.frame_count, sample_count=self.limits.sample_count
        )
        try:
            frames = self.reader.read_frames(media_root, relative, indices)
        except MediaAnalysisError:
            raise
        except Exception:
            raise MediaAnalysisError("frame_decode_failed") from None
        self._check_budget(started)
        self._check_frames(frames, metadata, indices)
        facts = tuple(self._facts(frame) for frame in frames)
        self._check_budget(started)
        return self._result(facts, metadata, target_duration_seconds, expected_objects, indices)

    def _check_metadata(self, metadata: MediaMetadata) -> None:
        if (
            metadata.width < 1
            or metadata.height < 1
            or metadata.frame_count < 1
            or not math.isfinite(metadata.duration_seconds)
            or not math.isfinite(metadata.fps)
            or metadata.duration_seconds <= 0
            or metadata.fps <= 0
        ):
            raise MediaAnalysisError("malformed_media_metadata")
        if metadata.byte_size < 1:
            raise MediaAnalysisError("malformed_media_metadata")
        if metadata.byte_size > self.limits.max_media_bytes:
            raise MediaAnalysisError("media_size_limit")
        if metadata.frame_count > self.limits.max_frame_count:
            raise MediaAnalysisError("frame_count_limit")
        if metadata.duration_seconds > self.limits.max_duration_seconds:
            raise MediaAnalysisError("duration_limit")
        if metadata.width * metadata.height > self.limits.max_pixels_per_frame:
            raise MediaAnalysisError("dimension_limit")

    def _check_frames(
        self,
        frames: tuple[FrameSample, ...],
        metadata: MediaMetadata,
        indices: tuple[int, ...],
    ) -> None:
        if len(frames) != len(indices):
            raise MediaAnalysisError("frame_decode_failed")
        previous_timestamp = -1.0
        for expected_index, frame in zip(indices, frames, strict=True):
            if (
                frame.index != expected_index
                or frame.width != metadata.width
                or frame.height != metadata.height
                or not math.isfinite(frame.timestamp_seconds)
                or frame.timestamp_seconds < previous_timestamp
                or len(frame.pixels) != frame.width * frame.height * 3
            ):
                raise MediaAnalysisError("malformed_frame")
            previous_timestamp = frame.timestamp_seconds

    def _check_budget(self, started: float) -> None:
        if self.monotonic() - started > self.limits.max_analysis_seconds:
            raise MediaAnalysisError("analysis_time_limit")

    def _facts(self, frame: FrameSample) -> _FrameFacts:
        pixels = frame.pixels
        quantized = Counter(
            (pixels[offset] // 32, pixels[offset + 1] // 32, pixels[offset + 2] // 32)
            for offset in range(0, len(pixels), 3)
        )
        background_bucket = quantized.most_common(1)[0][0]
        background = tuple(value * 32 + 16 for value in background_bucket)
        active: list[bool] = []
        boxes: dict[tuple[int, int, int], list[int]] = {}
        edge_count = 0
        for index in range(frame.width * frame.height):
            offset = index * 3
            rgb = (pixels[offset], pixels[offset + 1], pixels[offset + 2])
            is_active = max(abs(rgb[channel] - background[channel]) for channel in range(3)) >= (
                self.limits.contrast_delta
            )
            active.append(is_active)
            if not is_active:
                continue
            x, y = index % frame.width, index // frame.width
            if x in (0, frame.width - 1) or y in (0, frame.height - 1):
                edge_count += 1
            bucket = tuple(value // 64 for value in rgb)
            if bucket not in boxes:
                boxes[bucket] = [x, y, x, y, 0]
            box = boxes[bucket]
            box[0], box[1] = min(box[0], x), min(box[1], y)
            box[2], box[3], box[4] = max(box[2], x), max(box[3], y), box[4] + 1
        color_boxes = tuple(
            (bucket, (value[0], value[1], value[2], value[3]), value[4])
            for bucket, value in sorted(boxes.items())
            if value[4] >= 4
        )
        return _FrameFacts(
            frame=frame,
            active=tuple(active),
            active_count=sum(active),
            edge_count=edge_count,
            color_boxes=color_boxes,
            fingerprint=self._fingerprint(frame, tuple(active)),
            small_component_count=self._small_components(tuple(active), frame.width, frame.height),
            tofu_component_count=self._tofu_components(tuple(active), frame.width, frame.height),
        )

    @staticmethod
    def _fingerprint(frame: FrameSample, active: tuple[bool, ...]) -> bytes:
        """Describe foreground occupancy and color per cell, not a few fragile point samples."""
        columns, rows = 12, 8
        counts = [0] * (columns * rows)
        rgb_sums = [[0, 0, 0] for _ in counts]
        for index, is_active in enumerate(active):
            if not is_active:
                continue
            x, y = index % frame.width, index // frame.width
            cell = min(rows - 1, y * rows // frame.height) * columns + min(
                columns - 1, x * columns // frame.width
            )
            counts[cell] += 1
            offset = index * 3
            for channel in range(3):
                rgb_sums[cell][channel] += frame.pixels[offset + channel]
        cell_area = max(1, frame.width * frame.height // len(counts))
        values = bytearray()
        for count, sums in zip(counts, rgb_sums, strict=True):
            values.append(min(255, round(255 * count / cell_area)))
            values.extend(round(value / count / 8) if count else 0 for value in sums)
        return bytes(values)

    def _small_components(self, active: tuple[bool, ...], width: int, height: int) -> int:
        return sum(
            1
            for left, top, right, bottom, area in self._components(active, width, height)
            if area <= 16 and right - left <= 2 and bottom - top <= 2
        )

    def _tofu_components(self, active: tuple[bool, ...], width: int, height: int) -> int:
        shapes: Counter[tuple[int, int]] = Counter()
        for left, top, right, bottom, area in self._components(active, width, height):
            component_width, component_height = right - left + 1, bottom - top + 1
            rectangle = component_width * component_height
            if rectangle < 25 or area * 2 > rectangle + 2:
                continue
            if abs(component_width - component_height) > max(2, component_width // 2):
                continue
            horizontal = sum(active[top * width + x] for x in range(left, right + 1)) + sum(
                active[bottom * width + x] for x in range(left, right + 1)
            )
            vertical = sum(active[y * width + left] for y in range(top, bottom + 1)) + sum(
                active[y * width + right] for y in range(top, bottom + 1)
            )
            border_slots = 2 * component_width + 2 * component_height
            if horizontal + vertical < border_slots * 0.7:
                continue
            inner_slots = max(0, component_width - 2) * max(0, component_height - 2)
            inner_active = sum(
                active[y * width + x]
                for y in range(top + 1, bottom)
                for x in range(left + 1, right)
            )
            if inner_slots and inner_active / inner_slots <= 0.2:
                shapes[(component_width, component_height)] += 1
        return max(shapes.values(), default=0)

    @staticmethod
    def _components(
        active: tuple[bool, ...], width: int, height: int
    ) -> Iterable[tuple[int, int, int, int, int]]:
        visited = bytearray(len(active))
        for start, is_active in enumerate(active):
            if not is_active or visited[start]:
                continue
            queue = deque([start])
            visited[start] = 1
            left = right = start % width
            top = bottom = start // width
            area = 0
            while queue:
                index = queue.popleft()
                x, y = index % width, index // width
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
                area += 1
                for neighbor in (index - 1, index + 1, index - width, index + width):
                    if (
                        neighbor < 0
                        or neighbor >= len(active)
                        or visited[neighbor]
                        or not active[neighbor]
                    ):
                        continue
                    neighbor_x, neighbor_y = neighbor % width, neighbor // width
                    if abs(neighbor_x - x) + abs(neighbor_y - y) != 1:
                        continue
                    visited[neighbor] = 1
                    queue.append(neighbor)
            yield left, top, right, bottom, area

    def _result(
        self,
        facts: tuple[_FrameFacts, ...],
        metadata: MediaMetadata,
        target_duration_seconds: float,
        expected_objects: tuple[ExpectedObjectProxy, ...],
        indices: tuple[int, ...],
    ) -> VisualAnalysisResult:
        records: list[tuple[str, str, str, float | int | None, float | int | None]] = []
        blank_count = sum(
            fact.active_count / (fact.frame.width * fact.frame.height)
            <= self.limits.blank_active_ratio
            for fact in facts
        )
        if blank_count and blank_count / len(facts) >= 0.2:
            records.append(
                ("blank_frame", "error", "Sampled blank frames detected.", blank_count, len(facts))
            )
        longest_static = self._longest_static_seconds(facts, metadata.fps)
        static_limit = min(
            max(self.limits.static_threshold_seconds, target_duration_seconds * 0.2),
            target_duration_seconds,
        )
        if longest_static > static_limit:
            records.append(
                (
                    "long_static_segment",
                    "error",
                    "Long static sampled interval detected.",
                    longest_static,
                    static_limit,
                )
            )
        edge_count = max((fact.edge_count for fact in facts), default=0)
        if edge_count >= self.limits.edge_contact_pixels:
            records.append(
                (
                    "object_out_of_bounds",
                    "error",
                    "Foreground contacts the frame edge.",
                    edge_count,
                    self.limits.edge_contact_pixels,
                )
            )
        if any(self._has_overlap_proxy(fact) for fact in facts):
            records.append(
                (
                    "object_overlap",
                    "warning",
                    "Overlapping colored-object proxy detected.",
                    None,
                    None,
                )
            )
        small_count = max((fact.small_component_count for fact in facts), default=0)
        if small_count >= self.limits.min_small_text_components:
            records.append(
                (
                    "text_too_small",
                    "warning",
                    "Small text proxy components detected.",
                    small_count,
                    self.limits.min_small_text_components,
                )
            )
        tofu_count = max((fact.tofu_component_count for fact in facts), default=0)
        if tofu_count >= self.limits.min_tofu_components:
            records.append(
                (
                    "cjk_glyph_missing",
                    "error",
                    "Missing-glyph box proxy detected.",
                    tofu_count,
                    self.limits.min_tofu_components,
                )
            )
        for expected in expected_objects:
            visible = sum(self._matching_pixels(fact.frame, expected.rgb) for fact in facts)
            if visible < expected.min_visible_pixels:
                records.append(
                    (
                        "object_missing",
                        "error",
                        "Expected object proxy is not visible.",
                        visible,
                        expected.min_visible_pixels,
                    )
                )
        return self._build_result(records, indices)

    @staticmethod
    def _longest_static_seconds(facts: tuple[_FrameFacts, ...], fps: float) -> float:
        if not facts:
            return 0.0
        longest = current = 1.0 / fps
        for previous, current_fact in zip(facts, facts[1:], strict=False):
            interval = max(
                0.0, current_fact.frame.timestamp_seconds - previous.frame.timestamp_seconds
            )
            if previous.fingerprint == current_fact.fingerprint:
                current += interval
            else:
                current = 1.0 / fps
            longest = max(longest, current)
        return round(longest, 6)

    @staticmethod
    def _box_intersects(
        first: tuple[int, int, int, int], second: tuple[int, int, int, int]
    ) -> bool:
        return not (
            first[2] < second[0]
            or second[2] < first[0]
            or first[3] < second[1]
            or second[3] < first[1]
        )

    def _has_overlap_proxy(self, fact: _FrameFacts) -> bool:
        meaningful = [entry for entry in fact.color_boxes if entry[2] >= 8]
        return any(
            sum(abs(first[0][channel] - second[0][channel]) for channel in range(3)) >= 4
            and max(first[0]) == 3
            and max(second[0]) == 3
            and max(first[0]) - min(first[0]) >= 2
            and max(second[0]) - min(second[0]) >= 2
            and self._box_intersects(first[1], second[1])
            for position, first in enumerate(meaningful)
            for second in meaningful[position + 1 :]
        )

    @staticmethod
    def _matching_pixels(frame: FrameSample, expected: tuple[int, int, int]) -> int:
        return sum(
            max(abs(frame.pixels[offset + channel] - expected[channel]) for channel in range(3))
            <= 24
            for offset in range(0, len(frame.pixels), 3)
        )

    @staticmethod
    def _build_result(
        records: list[tuple[str, str, str, float | int | None, float | int | None]],
        indices: tuple[int, ...],
    ) -> VisualAnalysisResult:
        normalized = sorted(records, key=lambda item: (item[0], item[3] or -1, item[4] or -1))
        evidence: list[VisualEvidence] = []
        diagnostics: list[VisualDiagnostic] = []
        for code, severity, summary, measured, threshold in normalized:
            payload = {
                "code": code,
                "measured": measured,
                "sampled_frame_indices": indices,
                "threshold": threshold,
            }
            digest = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            reference = f"visual/{digest[:24]}.json"
            evidence.append(VisualEvidence(reference, indices, f"{code}: sampled-frame summary"))
            diagnostics.append(
                VisualDiagnostic(code, severity, reference, summary, measured, threshold)
            )
        signature_payload = [
            (item.code, item.severity, item.measured_value, item.threshold_value, item.evidence_ref)
            for item in diagnostics
        ]
        signature = hashlib.sha256(
            json.dumps(signature_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return VisualAnalysisResult(tuple(diagnostics), tuple(evidence), signature, indices)
