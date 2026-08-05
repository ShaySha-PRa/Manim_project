"""Deterministic, non-executing temporal diagnostics for approved Manim source.

This module intentionally owns only internal Phase 9 types.  It does not persist
reports or depend on the shared schema so the parent integration layer can adapt
the results without making this parser an authorization or storage boundary.
"""

from __future__ import annotations

import ast
import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Final

from manim_workbench_api.code_generation.security import validate_source_security

DEFAULT_PLAY_DURATION_SECONDS: Final = 1.0
DEFAULT_WAIT_DURATION_SECONDS: Final = 1.0
TARGET_DURATION_TOLERANCE: Final = 0.10
LONG_STATIC_TARGET_RATIO: Final = 0.20
TERMINAL_PADDING_SECONDS: Final = 5.0

_ANIMATION_GROUP_NAMES: Final = frozenset({"AnimationGroup", "LaggedStart", "Succession"})
_MOBJECT_FACTORIES: Final = frozenset(
    {
        "Arrow",
        "Axes",
        "DashedLine",
        "DecimalNumber",
        "Dot",
        "Line",
        "MathTex",
        "NumberLine",
        "NumberPlane",
        "Rectangle",
        "SurroundingRectangle",
        "Text",
        "VGroup",
        "ValueTracker",
    }
)
_FORMULA_FACTORIES: Final = frozenset({"MathTex", "Tex", "Text"})
_IDENTIFIER: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")


class DiagnosticCode(str, Enum):
    """Stable internal diagnostic identifiers, suitable for schema adaptation."""

    SOURCE_NOT_APPROVED = "source_not_approved"
    TIMELINE_UNKNOWN = "timeline_unknown"
    DEFAULT_PLAY_DURATION_ASSUMED = "default_play_duration_assumed"
    DURATION_TOO_SHORT = "duration_too_short"
    DURATION_TOO_LONG = "duration_too_long"
    LONG_STATIC_SEGMENT = "long_static_segment"
    TERMINAL_WAIT_PADDING = "terminal_wait_padding"
    MEDIA_METADATA_INVALID = "media_metadata_invalid"
    MEDIA_METADATA_INCONSISTENT = "media_metadata_inconsistent"
    PREVIEW_FINAL_TIMELINE_MISMATCH = "preview_final_timeline_mismatch"
    PLANNED_SCENE_MISSING = "planned_scene_missing"
    KEY_FORMULA_MISSING = "key_formula_missing"
    OBJECT_MISSING = "object_missing"
    ANIMATION_ORDER_MISMATCH = "animation_order_mismatch"


class DiagnosticSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class TimelineEventKind(str, Enum):
    PLAY = "play"
    WAIT = "wait"


class TimelineDurationOrigin(str, Enum):
    EXPLICIT_PLAY = "explicit_play"
    EXPLICIT_GROUP = "explicit_group"
    EXPLICIT_WAIT = "explicit_wait"
    DEFAULT_PLAY = "default_play"
    DEFAULT_WAIT = "default_wait"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TimelineDiagnostic:
    code: DiagnosticCode
    severity: DiagnosticSeverity
    message: str
    measured_value: float | None = None
    threshold_value: float | None = None


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    index: int
    kind: TimelineEventKind
    duration_seconds: float | None
    origin: TimelineDurationOrigin


@dataclass(frozen=True, slots=True)
class MediaTiming:
    """Runner-probed media timing.  Values are diagnosed, not trusted blindly."""

    duration_seconds: float | None
    frame_rate: float | None
    frame_count: int | None


@dataclass(frozen=True, slots=True)
class PlanSceneExpectation:
    """Minimal plan facts needed for source-only consistency checks."""

    scene_number: int
    required_formula_expressions: tuple[str, ...] = ()
    required_objects: tuple[str, ...] = ()
    animation_sequence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContentPlanExpectation:
    scenes: tuple[PlanSceneExpectation, ...]


@dataclass(frozen=True, slots=True)
class SanitizedSourceMetadata:
    """Source-derived facts only; this deliberately never stores source text."""

    source_sha256: str
    object_names: tuple[str, ...]
    formula_digests: tuple[str, ...]
    animation_sequence: tuple[str, ...]
    teaching_beat_count: int


@dataclass(frozen=True, slots=True)
class TemporalQualityReport:
    source_metadata: SanitizedSourceMetadata
    source_approved: bool
    target_duration_seconds: float
    estimated_duration_seconds: float | None
    actual_duration_seconds: float | None
    events: tuple[TimelineEvent, ...]
    diagnostics: tuple[TimelineDiagnostic, ...]


def analyze_temporal_quality(
    source: object,
    *,
    target_duration_seconds: float,
    actual_media: MediaTiming | None = None,
    preview_media: MediaTiming | None = None,
    final_media: MediaTiming | None = None,
    content_plan: ContentPlanExpectation | None = None,
) -> TemporalQualityReport:
    """Analyze approved source and media metadata without importing or executing source.

    `validate_source_security` is intentionally invoked before `ast.parse`.  Thus a
    Phase 7 policy rejection never gets a partial timeline interpretation.
    """
    target = _positive_finite(target_duration_seconds, "target_duration_seconds")
    security_report = validate_source_security(source)  # type: ignore[arg-type]
    if not security_report.allowed:
        metadata = SanitizedSourceMetadata(
            source_sha256=security_report.source_sha256,
            object_names=(),
            formula_digests=(),
            animation_sequence=(),
            teaching_beat_count=0,
        )
        return TemporalQualityReport(
            source_metadata=metadata,
            source_approved=False,
            target_duration_seconds=target,
            estimated_duration_seconds=None,
            actual_duration_seconds=None,
            events=(),
            diagnostics=(
                TimelineDiagnostic(
                    code=DiagnosticCode.SOURCE_NOT_APPROVED,
                    severity=DiagnosticSeverity.ERROR,
                    message="Timeline analysis requires an approved static source policy result.",
                ),
            ),
        )

    try:
        tree = ast.parse(source, filename="<approved-generated-source>", mode="exec")
    except (MemoryError, RecursionError, SyntaxError, TypeError, ValueError):
        # Defense in depth: do not surface parser details or source fragments.
        metadata = SanitizedSourceMetadata(
            source_sha256=security_report.source_sha256,
            object_names=(),
            formula_digests=(),
            animation_sequence=(),
            teaching_beat_count=0,
        )
        return TemporalQualityReport(
            source_metadata=metadata,
            source_approved=False,
            target_duration_seconds=target,
            estimated_duration_seconds=None,
            actual_duration_seconds=None,
            events=(),
            diagnostics=(
                TimelineDiagnostic(
                    code=DiagnosticCode.SOURCE_NOT_APPROVED,
                    severity=DiagnosticSeverity.ERROR,
                    message="Timeline analysis could not parse approved source safely.",
                ),
            ),
        )

    visitor = _TimelineVisitor()
    visitor.visit_construct(tree)
    metadata = _metadata_from_tree(tree, security_report.source_sha256, visitor.events)
    diagnostics = list(visitor.diagnostics)
    estimated = _estimated_duration(visitor.events)
    if estimated is not None:
        _append_target_duration_diagnostic(diagnostics, estimated, target)
        _append_static_padding_diagnostics(diagnostics, visitor.events, estimated, target)

    actual_duration = _append_media_diagnostics(
        diagnostics, actual_media, target=target, compare_to_target=True
    )
    _append_preview_final_diagnostic(diagnostics, preview_media, final_media)
    if content_plan is not None:
        _append_content_plan_diagnostics(diagnostics, content_plan, metadata, visitor.events)

    return TemporalQualityReport(
        source_metadata=metadata,
        source_approved=True,
        target_duration_seconds=target,
        estimated_duration_seconds=estimated,
        actual_duration_seconds=actual_duration,
        events=tuple(visitor.events),
        diagnostics=tuple(diagnostics),
    )


class _TimelineVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.events: list[TimelineEvent] = []
        self.diagnostics: list[TimelineDiagnostic] = []
        self._control_flow_depth = 0

    def visit_construct(self, tree: ast.Module) -> None:
        construct = _generated_scene_construct(tree)
        if construct is None:
            return
        for statement in construct.body:
            self.visit(statement)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        # Nested helpers are not guaranteed to execute; never estimate them.
        del node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        del node

    def visit_For(self, node: ast.For) -> None:  # noqa: N802
        self._visit_dynamic_control(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:  # noqa: N802
        self._visit_dynamic_control(node)

    def visit_While(self, node: ast.While) -> None:  # noqa: N802
        self._visit_dynamic_control(node)

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        self._visit_dynamic_control(node)

    def visit_Try(self, node: ast.Try) -> None:  # noqa: N802
        self._visit_dynamic_control(node)

    def visit_With(self, node: ast.With) -> None:  # noqa: N802
        self._visit_dynamic_control(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:  # noqa: N802
        self._visit_dynamic_control(node)

    def visit_Match(self, node: ast.Match) -> None:  # noqa: N802
        self._visit_dynamic_control(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        method_name = _self_method_name(node.func)
        if method_name == "play":
            self._record_play(node)
            return
        if method_name == "wait":
            self._record_wait(node)
            return
        self.generic_visit(node)

    def _visit_dynamic_control(self, node: ast.AST) -> None:
        self._control_flow_depth += 1
        try:
            self.generic_visit(node)
        finally:
            self._control_flow_depth -= 1

    def _record_play(self, node: ast.Call) -> None:
        if self._control_flow_depth:
            self._unknown_event(TimelineEventKind.PLAY, "control-flow-dependent play duration")
            return
        duration, origin, reason = _play_duration(node)
        if reason is not None:
            self._unknown_event(TimelineEventKind.PLAY, reason)
            return
        self._append_event(TimelineEventKind.PLAY, duration, origin)
        if origin is TimelineDurationOrigin.DEFAULT_PLAY:
            self.diagnostics.append(
                TimelineDiagnostic(
                    code=DiagnosticCode.DEFAULT_PLAY_DURATION_ASSUMED,
                    severity=DiagnosticSeverity.WARNING,
                    message="A play call used the conservative default duration.",
                    measured_value=DEFAULT_PLAY_DURATION_SECONDS,
                )
            )

    def _record_wait(self, node: ast.Call) -> None:
        if self._control_flow_depth:
            self._unknown_event(TimelineEventKind.WAIT, "control-flow-dependent wait duration")
            return
        duration, origin, reason = _wait_duration(node)
        if reason is not None:
            self._unknown_event(TimelineEventKind.WAIT, reason)
            return
        self._append_event(TimelineEventKind.WAIT, duration, origin)

    def _append_event(
        self,
        kind: TimelineEventKind,
        duration: float,
        origin: TimelineDurationOrigin,
    ) -> None:
        self.events.append(
            TimelineEvent(
                index=len(self.events) + 1,
                kind=kind,
                duration_seconds=duration,
                origin=origin,
            )
        )

    def _unknown_event(self, kind: TimelineEventKind, reason: str) -> None:
        self.events.append(
            TimelineEvent(
                index=len(self.events) + 1,
                kind=kind,
                duration_seconds=None,
                origin=TimelineDurationOrigin.UNKNOWN,
            )
        )
        self.diagnostics.append(
            TimelineDiagnostic(
                code=DiagnosticCode.TIMELINE_UNKNOWN,
                severity=DiagnosticSeverity.ERROR,
                message=f"Timeline duration is unknown because of {reason}.",
            )
        )


def _self_method_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
        return None
    return node.attr if node.value.id == "self" else None


def _generated_scene_construct(tree: ast.Module) -> ast.FunctionDef | None:
    scene = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "GeneratedScene"
        ),
        None,
    )
    if scene is None:
        return None
    return next(
        (
            node
            for node in scene.body
            if isinstance(node, ast.FunctionDef) and node.name == "construct"
        ),
        None,
    )


def _play_duration(
    node: ast.Call,
) -> tuple[float | None, TimelineDurationOrigin, str | None]:
    outer, outer_error = _keyword_duration(node.keywords, "run_time")
    if outer_error is not None:
        return None, TimelineDurationOrigin.UNKNOWN, outer_error
    if outer is not None:
        return outer, TimelineDurationOrigin.EXPLICIT_PLAY, None
    if any(isinstance(argument, ast.Starred) for argument in node.args):
        return None, TimelineDurationOrigin.UNKNOWN, "dynamic animation argument expansion"

    durations: list[float] = []
    group_duration_found = False
    for argument in node.args:
        if not isinstance(argument, ast.Call):
            return None, TimelineDurationOrigin.UNKNOWN, "dynamic animation argument"
        function_name = _call_name(argument.func)
        if function_name in _ANIMATION_GROUP_NAMES:
            group_duration, group_error = _keyword_duration(argument.keywords, "run_time")
            if group_error is not None:
                return None, TimelineDurationOrigin.UNKNOWN, group_error
            if group_duration is not None:
                durations.append(group_duration)
                group_duration_found = True
            else:
                durations.append(DEFAULT_PLAY_DURATION_SECONDS)
        else:
            durations.append(DEFAULT_PLAY_DURATION_SECONDS)
    if not durations:
        return DEFAULT_PLAY_DURATION_SECONDS, TimelineDurationOrigin.DEFAULT_PLAY, None
    if group_duration_found:
        return max(durations), TimelineDurationOrigin.EXPLICIT_GROUP, None
    return DEFAULT_PLAY_DURATION_SECONDS, TimelineDurationOrigin.DEFAULT_PLAY, None


def _wait_duration(
    node: ast.Call,
) -> tuple[float | None, TimelineDurationOrigin, str | None]:
    if len(node.args) > 1 or any(isinstance(argument, ast.Starred) for argument in node.args):
        return None, TimelineDurationOrigin.UNKNOWN, "dynamic wait arguments"
    duration_keyword, keyword_error = _keyword_duration(node.keywords, "duration")
    if keyword_error is not None:
        return None, TimelineDurationOrigin.UNKNOWN, keyword_error
    unsupported_keywords = [
        keyword for keyword in node.keywords if keyword.arg not in {"duration", "frozen_frame"}
    ]
    if unsupported_keywords:
        return None, TimelineDurationOrigin.UNKNOWN, "unsupported wait keyword"
    frozen_frame = next(
        (keyword.value for keyword in node.keywords if keyword.arg == "frozen_frame"), None
    )
    if frozen_frame is not None and not _is_bool_literal(frozen_frame):
        return None, TimelineDurationOrigin.UNKNOWN, "dynamic frozen-frame value"
    if node.args and duration_keyword is not None:
        return None, TimelineDurationOrigin.UNKNOWN, "duplicate wait duration"
    if node.args:
        duration = _literal_duration(node.args[0])
        if duration is None:
            return None, TimelineDurationOrigin.UNKNOWN, "dynamic wait duration"
        return duration, TimelineDurationOrigin.EXPLICIT_WAIT, None
    if duration_keyword is not None:
        return duration_keyword, TimelineDurationOrigin.EXPLICIT_WAIT, None
    return DEFAULT_WAIT_DURATION_SECONDS, TimelineDurationOrigin.DEFAULT_WAIT, None


def _keyword_duration(
    keywords: list[ast.keyword],
    name: str,
) -> tuple[float | None, str | None]:
    matches = [keyword for keyword in keywords if keyword.arg == name]
    if len(matches) > 1:
        return None, f"duplicate {name} keyword"
    if any(keyword.arg is None for keyword in keywords):
        return None, "dynamic keyword expansion"
    if not matches:
        return None, None
    value = _literal_duration(matches[0].value)
    if value is None:
        return None, f"dynamic {name} value"
    return value, None


def _literal_duration(node: ast.AST) -> float | None:
    if not isinstance(node, ast.Constant) or isinstance(node.value, bool):
        return None
    if not isinstance(node.value, int | float):
        return None
    value = float(node.value)
    return value if math.isfinite(value) and value >= 0 else None


def _is_bool_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, bool)


def _call_name(node: ast.AST) -> str | None:
    return node.id if isinstance(node, ast.Name) else None


def _estimated_duration(events: list[TimelineEvent]) -> float | None:
    if any(event.duration_seconds is None for event in events):
        return None
    return sum(event.duration_seconds or 0.0 for event in events)


def _append_target_duration_diagnostic(
    diagnostics: list[TimelineDiagnostic], value: float, target: float
) -> None:
    lower, upper = _target_bounds(target)
    if value < lower:
        diagnostics.append(
            TimelineDiagnostic(
                code=DiagnosticCode.DURATION_TOO_SHORT,
                severity=DiagnosticSeverity.ERROR,
                message="Duration is below the configured target tolerance.",
                measured_value=value,
                threshold_value=lower,
            )
        )
    elif value > upper:
        diagnostics.append(
            TimelineDiagnostic(
                code=DiagnosticCode.DURATION_TOO_LONG,
                severity=DiagnosticSeverity.ERROR,
                message="Duration is above the configured target tolerance.",
                measured_value=value,
                threshold_value=upper,
            )
        )


def _append_static_padding_diagnostics(
    diagnostics: list[TimelineDiagnostic],
    events: list[TimelineEvent],
    estimated: float,
    target: float,
) -> None:
    longest_wait = max(
        (event.duration_seconds or 0.0 for event in events if event.kind is TimelineEventKind.WAIT),
        default=0.0,
    )
    static_threshold = target * LONG_STATIC_TARGET_RATIO
    if longest_wait > static_threshold:
        diagnostics.append(
            TimelineDiagnostic(
                code=DiagnosticCode.LONG_STATIC_SEGMENT,
                severity=DiagnosticSeverity.ERROR,
                message="A static wait exceeds the allowed fraction of the target duration.",
                measured_value=longest_wait,
                threshold_value=static_threshold,
            )
        )
    if not events or events[-1].kind is not TimelineEventKind.WAIT:
        return
    terminal_wait = events[-1].duration_seconds or 0.0
    lower, _ = _target_bounds(target)
    non_terminal_duration = estimated - terminal_wait
    if terminal_wait > TERMINAL_PADDING_SECONDS and non_terminal_duration < lower <= estimated:
        diagnostics.append(
            TimelineDiagnostic(
                code=DiagnosticCode.TERMINAL_WAIT_PADDING,
                severity=DiagnosticSeverity.ERROR,
                message="A terminal wait appears to be padding the target duration.",
                measured_value=terminal_wait,
                threshold_value=TERMINAL_PADDING_SECONDS,
            )
        )


def _append_media_diagnostics(
    diagnostics: list[TimelineDiagnostic],
    media: MediaTiming | None,
    *,
    target: float,
    compare_to_target: bool,
) -> float | None:
    if media is None:
        return None
    valid, duration = _validate_media_timing(diagnostics, media)
    if compare_to_target and valid and duration is not None:
        _append_target_duration_diagnostic(diagnostics, duration, target)
    return duration


def _validate_media_timing(
    diagnostics: list[TimelineDiagnostic], media: MediaTiming
) -> tuple[bool, float | None]:
    duration = _nonnegative_finite(media.duration_seconds)
    fps = _positive_optional_finite(media.frame_rate)
    valid_count = isinstance(media.frame_count, int) and not isinstance(media.frame_count, bool)
    if valid_count and media.frame_count is not None:
        valid_count = media.frame_count >= 0
    if duration is None or fps is None or not valid_count or media.frame_count == 0:
        diagnostics.append(
            TimelineDiagnostic(
                code=DiagnosticCode.MEDIA_METADATA_INVALID,
                severity=DiagnosticSeverity.ERROR,
                message="Media duration, frame rate, or frame count is invalid.",
            )
        )
        return False, duration
    if media.frame_count is not None:
        derived_duration = media.frame_count / fps
        if abs(duration - derived_duration) > 1 / fps:
            diagnostics.append(
                TimelineDiagnostic(
                    code=DiagnosticCode.MEDIA_METADATA_INCONSISTENT,
                    severity=DiagnosticSeverity.ERROR,
                    message="Container duration and frame metadata differ by more than one frame.",
                    measured_value=abs(duration - derived_duration),
                    threshold_value=1 / fps,
                )
            )
            return False, duration
    return True, duration


def _append_preview_final_diagnostic(
    diagnostics: list[TimelineDiagnostic], preview: MediaTiming | None, final: MediaTiming | None
) -> None:
    if preview is None or final is None:
        return
    preview_valid, preview_duration = _validate_media_timing(diagnostics, preview)
    final_valid, final_duration = _validate_media_timing(diagnostics, final)
    if not preview_valid or not final_valid or preview_duration is None or final_duration is None:
        return
    preview_fps = float(preview.frame_rate)
    final_fps = float(final.frame_rate)
    tolerance = 1 / max(preview_fps, final_fps)
    difference = abs(preview_duration - final_duration)
    if difference - tolerance > 1e-9:
        diagnostics.append(
            TimelineDiagnostic(
                code=DiagnosticCode.PREVIEW_FINAL_TIMELINE_MISMATCH,
                severity=DiagnosticSeverity.ERROR,
                message="Preview and final timelines differ by more than one frame.",
                measured_value=difference,
                threshold_value=tolerance,
            )
        )


def _append_content_plan_diagnostics(
    diagnostics: list[TimelineDiagnostic],
    plan: ContentPlanExpectation,
    metadata: SanitizedSourceMetadata,
    events: list[TimelineEvent],
) -> None:
    scenes = tuple(sorted(plan.scenes, key=lambda scene: scene.scene_number))
    teaching_beats = len([event for event in events if event.kind is TimelineEventKind.PLAY])
    if teaching_beats < len(scenes):
        diagnostics.append(
            TimelineDiagnostic(
                code=DiagnosticCode.PLANNED_SCENE_MISSING,
                severity=DiagnosticSeverity.ERROR,
                message="The source has fewer teaching beats than planned scenes.",
                measured_value=float(teaching_beats),
                threshold_value=float(len(scenes)),
            )
        )
    expected_formulas = {
        _formula_digest(expression)
        for scene in scenes
        for expression in scene.required_formula_expressions
        if expression.strip()
    }
    if not expected_formulas.issubset(metadata.formula_digests):
        diagnostics.append(
            TimelineDiagnostic(
                code=DiagnosticCode.KEY_FORMULA_MISSING,
                severity=DiagnosticSeverity.ERROR,
                message="One or more planned formula expressions are absent from source metadata.",
                measured_value=float(len(expected_formulas - set(metadata.formula_digests))),
            )
        )
    expected_objects = {
        name for scene in scenes for name in scene.required_objects if _IDENTIFIER.fullmatch(name)
    }
    if not expected_objects.issubset(metadata.object_names):
        diagnostics.append(
            TimelineDiagnostic(
                code=DiagnosticCode.OBJECT_MISSING,
                severity=DiagnosticSeverity.ERROR,
                message="One or more planned visual objects are absent from source metadata.",
                measured_value=float(len(expected_objects - set(metadata.object_names))),
            )
        )
    expected_sequence = tuple(
        animation
        for scene in scenes
        for animation in scene.animation_sequence
        if _IDENTIFIER.fullmatch(animation)
    )
    if expected_sequence and not _is_subsequence(expected_sequence, metadata.animation_sequence):
        diagnostics.append(
            TimelineDiagnostic(
                code=DiagnosticCode.ANIMATION_ORDER_MISMATCH,
                severity=DiagnosticSeverity.ERROR,
                message="The planned animation sequence is missing or out of order.",
            )
        )


def _metadata_from_tree(
    tree: ast.Module, source_sha256: str, events: list[TimelineEvent]
) -> SanitizedSourceMetadata:
    collector = _SourceMetadataVisitor()
    construct = _generated_scene_construct(tree)
    if construct is not None:
        for statement in construct.body:
            collector.visit(statement)
    return SanitizedSourceMetadata(
        source_sha256=source_sha256,
        object_names=tuple(sorted(collector.object_names)),
        formula_digests=tuple(sorted(collector.formula_digests)),
        animation_sequence=tuple(collector.animation_sequence),
        teaching_beat_count=len(
            [event for event in events if event.kind is TimelineEventKind.PLAY]
        ),
    )


class _SourceMetadataVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.object_names: set[str] = set()
        self.formula_digests: set[str] = set()
        self.animation_sequence: list[str] = []

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        if isinstance(node.value, ast.Call) and _call_name(node.value.func) in _MOBJECT_FACTORIES:
            for target in node.targets:
                if isinstance(target, ast.Name) and _IDENTIFIER.fullmatch(target.id):
                    self.object_names.add(target.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        # A nested helper might never run, so it cannot satisfy a plan requirement.
        del node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        del node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        if (
            isinstance(node.target, ast.Name)
            and isinstance(node.value, ast.Call)
            and _call_name(node.value.func) in _MOBJECT_FACTORIES
            and _IDENTIFIER.fullmatch(node.target.id)
        ):
            self.object_names.add(node.target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        function_name = _call_name(node.func)
        if function_name in _FORMULA_FACTORIES:
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    self.formula_digests.add(_formula_digest(argument.value))
        if _self_method_name(node.func) == "play":
            for argument in node.args:
                self.animation_sequence.extend(_animation_names(argument))
        self.generic_visit(node)


def _animation_names(node: ast.AST) -> tuple[str, ...]:
    if not isinstance(node, ast.Call):
        return ()
    name = _call_name(node.func)
    if name is None:
        return ()
    if name in _ANIMATION_GROUP_NAMES:
        return tuple(child for argument in node.args for child in _animation_names(argument))
    return (name,)


def _formula_digest(expression: str) -> str:
    normalized = "".join(unicodedata.normalize("NFKC", expression).split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _is_subsequence(expected: tuple[str, ...], actual: tuple[str, ...]) -> bool:
    iterator = iter(actual)
    return all(any(candidate == wanted for candidate in iterator) for wanted in expected)


def _target_bounds(target: float) -> tuple[float, float]:
    return target * (1 - TARGET_DURATION_TOLERANCE), target * (1 + TARGET_DURATION_TOLERANCE)


def _positive_finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be a finite positive number")
    converted = float(value)
    if not math.isfinite(converted) or converted <= 0:
        raise ValueError(f"{field_name} must be a finite positive number")
    return converted


def _nonnegative_finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) and converted >= 0 else None


def _positive_optional_finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) and converted > 0 else None
