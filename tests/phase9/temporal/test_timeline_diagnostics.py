from __future__ import annotations

import pytest
from manim_workbench_api.quality.temporal import (
    ContentPlanExpectation,
    DiagnosticCode,
    MediaTiming,
    PlanSceneExpectation,
    TimelineEventKind,
    analyze_temporal_quality,
)


def _source(body: str) -> str:
    return "\n".join(
        (
            "from manim import AnimationGroup, Create, Scene, Text, Write",
            "",
            "class GeneratedScene(Scene):",
            "    def construct(self):",
            body,
            "",
        )
    )


def _codes(report: object) -> set[DiagnosticCode]:
    return {diagnostic.code for diagnostic in report.diagnostics}  # type: ignore[attr-defined]


def test_estimates_direct_play_animation_group_and_wait_without_execution() -> None:
    source = _source(
        "        title = Text('x^2')\n"
        "        self.play(Write(title), run_time=2.5)\n"
        "        self.play(AnimationGroup(Write(title), run_time=3.0))\n"
        "        self.play(Write(title))\n"
        "        self.wait(2.0)"
    )

    report = analyze_temporal_quality(source, target_duration_seconds=9)

    assert report.estimated_duration_seconds == 8.5
    assert [event.kind for event in report.events] == [
        TimelineEventKind.PLAY,
        TimelineEventKind.PLAY,
        TimelineEventKind.PLAY,
        TimelineEventKind.WAIT,
    ]
    assert [event.duration_seconds for event in report.events] == [2.5, 3.0, 1.0, 2.0]
    assert report.source_metadata.source_sha256
    assert DiagnosticCode.TIMELINE_UNKNOWN not in _codes(report)


def test_dynamic_timeline_values_fail_closed_as_unknown() -> None:
    source = _source(
        "        title = Text('safe')\n"
        "        duration = 3\n"
        "        self.play(Write(title), run_time=duration)"
    )

    report = analyze_temporal_quality(source, target_duration_seconds=3)

    assert report.estimated_duration_seconds is None
    assert DiagnosticCode.TIMELINE_UNKNOWN in _codes(report)
    assert report.events[0].duration_seconds is None


def test_rejects_source_that_did_not_pass_the_approved_ast_policy() -> None:
    source = _source("        __import__('os').system('id')")

    report = analyze_temporal_quality(source, target_duration_seconds=30)

    assert report.estimated_duration_seconds is None
    assert DiagnosticCode.SOURCE_NOT_APPROVED in _codes(report)
    assert report.events == ()


def test_flags_target_duration_miss_and_terminal_wait_padding() -> None:
    source = _source(
        "        title = Text('x')\n"
        "        self.play(Write(title), run_time=80)\n"
        "        self.wait(12)"
    )

    report = analyze_temporal_quality(source, target_duration_seconds=90)

    assert report.estimated_duration_seconds == 92
    assert DiagnosticCode.TERMINAL_WAIT_PADDING in _codes(report)


def test_rejects_long_static_wait_even_when_total_duration_is_in_tolerance() -> None:
    source = _source(
        "        title = Text('x')\n"
        "        self.play(Write(title), run_time=80)\n"
        "        self.wait(19)"
    )

    report = analyze_temporal_quality(source, target_duration_seconds=90)

    assert report.estimated_duration_seconds == 99
    assert DiagnosticCode.LONG_STATIC_SEGMENT in _codes(report)
    assert DiagnosticCode.TERMINAL_WAIT_PADDING in _codes(report)


def test_compares_actual_media_duration_and_preview_final_timeline_to_one_frame() -> None:
    source = _source("        self.wait(90)")
    actual = MediaTiming(duration_seconds=9.6, frame_rate=15, frame_count=144)
    preview = MediaTiming(duration_seconds=90.0, frame_rate=15, frame_count=1350)
    final = MediaTiming(duration_seconds=90.1, frame_rate=60, frame_count=5406)

    report = analyze_temporal_quality(
        source,
        target_duration_seconds=90,
        actual_media=actual,
        preview_media=preview,
        final_media=final,
    )

    assert DiagnosticCode.DURATION_TOO_SHORT in _codes(report)
    assert DiagnosticCode.PREVIEW_FINAL_TIMELINE_MISMATCH in _codes(report)


def test_rejects_inconsistent_container_duration_and_frame_metadata() -> None:
    source = _source("        self.wait(10)")

    report = analyze_temporal_quality(
        source,
        target_duration_seconds=10,
        actual_media=MediaTiming(duration_seconds=10, frame_rate=10, frame_count=110),
    )

    assert DiagnosticCode.MEDIA_METADATA_INCONSISTENT in _codes(report)


@pytest.mark.parametrize(
    "media",
    [
        MediaTiming(duration_seconds=None, frame_rate=30, frame_count=300),
        MediaTiming(duration_seconds=10, frame_rate=0, frame_count=300),
        MediaTiming(duration_seconds=10, frame_rate=30, frame_count=-1),
        MediaTiming(duration_seconds=10, frame_rate=30, frame_count=0),
    ],
)
def test_rejects_missing_or_non_rendered_media_timing(media: MediaTiming) -> None:
    report = analyze_temporal_quality(
        _source("        self.wait(10)"),
        target_duration_seconds=10,
        actual_media=media,
    )

    assert DiagnosticCode.MEDIA_METADATA_INVALID in _codes(report)


def test_ignores_uninvoked_nested_helper_metadata_when_checking_the_plan() -> None:
    source = _source(
        "        title = Text('intro')\n"
        "        def unused_helper():\n"
        "            ghost = Text('y=x')\n"
        "            self.play(Write(ghost), run_time=99)\n"
        "        self.play(Write(title), run_time=1)"
    )
    plan = ContentPlanExpectation(
        scenes=(
            PlanSceneExpectation(
                scene_number=1,
                required_formula_expressions=("y=x",),
                required_objects=("ghost",),
                animation_sequence=("Write",),
            ),
        )
    )

    report = analyze_temporal_quality(source, target_duration_seconds=1, content_plan=plan)

    assert report.estimated_duration_seconds == 1
    assert DiagnosticCode.KEY_FORMULA_MISSING in _codes(report)
    assert DiagnosticCode.OBJECT_MISSING in _codes(report)


def test_allows_preview_final_duration_at_exactly_one_frame_difference() -> None:
    report = analyze_temporal_quality(
        _source("        self.wait(10)"),
        target_duration_seconds=10,
        preview_media=MediaTiming(duration_seconds=10, frame_rate=15, frame_count=150),
        final_media=MediaTiming(duration_seconds=10 + 1 / 60, frame_rate=60, frame_count=601),
    )

    assert DiagnosticCode.PREVIEW_FINAL_TIMELINE_MISMATCH not in _codes(report)


def test_checks_planned_scenes_formulas_objects_and_animation_order_from_sanitized_metadata() -> (
    None
):
    source = _source(
        "        title = Text('x^2')\n"
        "        axes = Text('axes')\n"
        "        graph = Text('graph')\n"
        "        self.play(Write(title), Create(axes), Create(graph), run_time=2)"
    )
    plan = ContentPlanExpectation(
        scenes=(
            PlanSceneExpectation(
                scene_number=1,
                required_formula_expressions=("x^2",),
                required_objects=("title", "axes", "graph"),
                animation_sequence=("Write", "Create", "Create"),
            ),
            PlanSceneExpectation(
                scene_number=2,
                required_formula_expressions=("y=x",),
                required_objects=("point",),
                animation_sequence=("Indicate",),
            ),
        )
    )

    report = analyze_temporal_quality(source, target_duration_seconds=2, content_plan=plan)

    codes = _codes(report)
    assert DiagnosticCode.PLANNED_SCENE_MISSING in codes
    assert DiagnosticCode.KEY_FORMULA_MISSING in codes
    assert DiagnosticCode.OBJECT_MISSING in codes
    assert DiagnosticCode.ANIMATION_ORDER_MISMATCH in codes
    assert not hasattr(report.source_metadata, "source")
    assert "x^2" not in repr(report.source_metadata)
