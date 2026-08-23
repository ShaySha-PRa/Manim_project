"""Pure, bounded repair and category-downgrade policy for Phase 7.

This module deliberately has no database, provider, renderer, or sandbox dependency.
Callers must persist decisions and invoke the renderer separately.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from manim_workbench_contracts import CodeGenerationCategory, CodeGenerationErrorCode


class CategoryPolicyState(str, Enum):
    """The persistent availability state for one generation category."""

    ACTIVE = "active"
    DEGRADED = "degraded"
    PAUSED = "paused"


class RepairAction(str, Enum):
    """The next deterministic action selected by the repair policy."""

    GENERATE = "generate"
    REPAIR = "repair"
    DETERMINISTIC_TEMPLATE = "deterministic_template"
    FAIL = "fail"
    PAUSE = "pause"


ErrorCode = CodeGenerationErrorCode | str


@dataclass(frozen=True)
class CategoryPolicy:
    """Per-category quality state; the policy is immutable from a caller's view."""

    state: CategoryPolicyState = CategoryPolicyState.ACTIVE
    consecutive_failed_quality_rounds: int = 0


@dataclass(frozen=True)
class RepairDecision:
    """A side-effect-free decision for the caller's next generation step."""

    action: RepairAction
    attempt_number: int
    error_code: ErrorCode | None = None
    include_candidate_source: bool = False
    category_state: CategoryPolicyState = CategoryPolicyState.ACTIVE
    template_metadata: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({}), compare=False
    )


_CATEGORIES = tuple(CodeGenerationCategory)
_REPAIRABLE_ERRORS = frozenset(
    {
        CodeGenerationErrorCode.INVALID_MODEL_RESPONSE,
        CodeGenerationErrorCode.RESPONSE_TOO_LARGE,
        CodeGenerationErrorCode.AST_PARSE_FAILED,
        CodeGenerationErrorCode.STATIC_POLICY_REPAIRABLE,
        CodeGenerationErrorCode.COMPILE_FAILED,
        CodeGenerationErrorCode.SCENE_STRUCTURE_INVALID,
        CodeGenerationErrorCode.RENDER_FAILED,
    }
)
_SOURCE_REPAIR_ERRORS = frozenset(
    {
        CodeGenerationErrorCode.SCENE_STRUCTURE_INVALID,
        CodeGenerationErrorCode.RENDER_FAILED,
    }
)
_MAX_ATTEMPTS = 3
_REPAIR_TEMPLATE_VERSION = "repair-v1"
_DETERMINISTIC_TEMPLATE_VERSION = "deterministic-v1"

_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_API_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b[A-Z][A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|AUTHORIZATION)"
    r"[A-Z0-9_]*\s*[:=]\s*\S+"
)
_URL = re.compile(r"(?i)\bhttps?://[^\s]+")
_WINDOWS_PATH = re.compile(r"(?i)\b[A-Z]:\\[^\s]+")
_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9_])/(?:[^\s:'\"()]+)")


def _metadata(**values: str) -> Mapping[str, str]:
    return MappingProxyType(dict(sorted(values.items())))


def _category(value: CodeGenerationCategory | str) -> CodeGenerationCategory:
    return value if isinstance(value, CodeGenerationCategory) else CodeGenerationCategory(value)


def _error_code(value: ErrorCode) -> ErrorCode:
    if isinstance(value, CodeGenerationErrorCode):
        return value
    try:
        return CodeGenerationErrorCode(value)
    except ValueError:
        return value


def _sanitize_diagnostic(value: str) -> str:
    """Return the bounded, secret-free diagnostic allowed into a repair prompt."""

    sanitized = value.replace("\x00", "")
    for pattern in (_BEARER_TOKEN, _API_KEY, _SECRET_ASSIGNMENT, _URL, _WINDOWS_PATH, _POSIX_PATH):
        sanitized = pattern.sub("[REDACTED]", sanitized)
    lines = sanitized.splitlines()[:20]
    return "\n".join(lines)[:4000]


class RepairOrchestrator:
    """Select bounded repair, degradation, and irreversible pause decisions."""

    def __init__(
        self,
        policies: Mapping[CodeGenerationCategory | str, CategoryPolicy] | None = None,
    ) -> None:
        supplied = policies or {}
        self._policies = {
            category: supplied.get(category, supplied.get(category.value, CategoryPolicy()))
            for category in _CATEGORIES
        }

    def category_policy(self, category: CodeGenerationCategory | str) -> CategoryPolicy:
        """Return a snapshot of the category policy state."""

        return self._policies[_category(category)]

    def initial_decision(self, category: CodeGenerationCategory | str) -> RepairDecision:
        """Select initial model generation, deterministic template, or a global pause."""

        resolved_category = _category(category)
        policy = self.category_policy(resolved_category)
        if self._globally_paused():
            return self._paused_decision(policy)
        if policy.state is CategoryPolicyState.DEGRADED:
            return RepairDecision(
                action=RepairAction.DETERMINISTIC_TEMPLATE,
                attempt_number=0,
                error_code=CodeGenerationErrorCode.CATEGORY_DEGRADED,
                category_state=policy.state,
                template_metadata=_metadata(
                    selection="category_degraded",
                    template_version=_DETERMINISTIC_TEMPLATE_VERSION,
                ),
            )
        return RepairDecision(
            action=RepairAction.GENERATE,
            attempt_number=1,
            category_state=policy.state,
            template_metadata=_metadata(selection="model", template_version="full-v1"),
        )

    def failure_decision(
        self,
        category: CodeGenerationCategory | str,
        *,
        attempt_number: int,
        error_code: ErrorCode,
    ) -> RepairDecision:
        """Classify a failed attempt without consuming a forbidden repair budget."""

        if not 1 <= attempt_number <= _MAX_ATTEMPTS:
            raise ValueError("attempt_number must be in the inclusive range 1..3")

        resolved_category = _category(category)
        policy = self.category_policy(resolved_category)
        if self._globally_paused():
            return self._paused_decision(policy, attempt_number=attempt_number)
        if policy.state is CategoryPolicyState.DEGRADED:
            return self.initial_decision(resolved_category)

        resolved_error = _error_code(error_code)
        if resolved_error not in _REPAIRABLE_ERRORS:
            return RepairDecision(
                action=RepairAction.FAIL,
                attempt_number=attempt_number,
                error_code=resolved_error,
                category_state=policy.state,
            )
        if attempt_number == _MAX_ATTEMPTS:
            return RepairDecision(
                action=RepairAction.FAIL,
                attempt_number=attempt_number,
                error_code=CodeGenerationErrorCode.ATTEMPT_BUDGET_EXHAUSTED,
                category_state=policy.state,
            )

        return RepairDecision(
            action=RepairAction.REPAIR,
            attempt_number=attempt_number + 1,
            error_code=resolved_error,
            include_candidate_source=resolved_error in _SOURCE_REPAIR_ERRORS,
            category_state=policy.state,
            template_metadata=_metadata(
                selection="error_category",
                template_version=_REPAIR_TEMPLATE_VERSION,
            ),
        )

    def record_quality_round(
        self, category: CodeGenerationCategory | str, *, passed: bool
    ) -> CategoryPolicy:
        """Record a final quality gate; two consecutive failures degrade one category."""

        resolved_category = _category(category)
        current = self.category_policy(resolved_category)
        if current.state is CategoryPolicyState.PAUSED:
            return current
        if passed:
            updated = CategoryPolicy()
        else:
            failures = current.consecutive_failed_quality_rounds + 1
            updated = CategoryPolicy(
                state=(
                    CategoryPolicyState.DEGRADED if failures >= 2 else CategoryPolicyState.ACTIVE
                ),
                consecutive_failed_quality_rounds=failures,
            )
        self._policies[resolved_category] = updated
        return updated

    def record_security_escape(self) -> None:
        """Permanently pause both categories until a parent-controlled policy reset."""

        self._policies = {
            category: CategoryPolicy(
                state=CategoryPolicyState.PAUSED,
                consecutive_failed_quality_rounds=policy.consecutive_failed_quality_rounds,
            )
            for category, policy in self._policies.items()
        }

    def _globally_paused(self) -> bool:
        return any(policy.state is CategoryPolicyState.PAUSED for policy in self._policies.values())

    @staticmethod
    def _paused_decision(policy: CategoryPolicy, *, attempt_number: int = 0) -> RepairDecision:
        return RepairDecision(
            action=RepairAction.PAUSE,
            attempt_number=attempt_number,
            error_code=CodeGenerationErrorCode.GENERATION_PAUSED,
            category_state=CategoryPolicyState.PAUSED,
        )


def build_repair_messages(
    *,
    content_plan: Mapping[str, object],
    decision: RepairDecision,
    diagnostic: str,
    candidate_source: str | None = None,
) -> tuple[dict[str, str], ...]:
    """Build a deterministic repair prompt from approved, sanitized context only.

    The function accepts only a decision that has already classified the error as
    repairable.  Security and infrastructure failures therefore cannot accidentally
    return a candidate or sensitive diagnostic to the model.
    """

    if decision.action is not RepairAction.REPAIR:
        raise ValueError("only a repair decision may build repair messages")
    if decision.include_candidate_source and candidate_source is None:
        raise ValueError("candidate_source is required for this repair category")

    system = (
        "Return only one JSON object with exactly these fields and no others: "
        '{"scene_class":"GeneratedScene","code":"...","assumptions":[]}. '
        "Do not use Markdown fences or text outside JSON. scene_class must be GeneratedScene; "
        "code must be complete replacement Python source containing exactly one GeneratedScene "
        "class inheriting Scene; assumptions must be an array of at most 20 short strings. "
        "Stay within the supplied ContentPlan and Manim 0.21.0 contract. "
        "Explicitly import every Manim symbol used with one `from manim import ...` statement; "
        "do not use any other imports. Allowed Manim symbols are Scene, Text, MathTex, VGroup, "
        "Axes, NumberPlane, NumberLine, Dot, Line, Arrow, DashedLine, Rectangle, "
        "SurroundingRectangle, DecimalNumber, ValueTracker, Write, Create, GrowArrow, FadeIn, "
        "FadeOut, Transform, ReplacementTransform, TransformMatchingTex, Indicate, "
        "AnimationGroup, LaggedStart, always_redraw, UP, DOWN, LEFT, RIGHT, WHITE, BLUE, GREEN, "
        "RED, YELLOW, ORANGE, PURPLE, GRAY, PI and TAU. Replace lambdas with a local named "
        "function. Use Text for both prose and formula strings; do not call MathTex. Keep readable "
        "Unicode math such as x², √, ±, ≤ and ≥ inside Text. Every Text object must set "
        'font="Noto Sans CJK SC". Never put Chinese text inside MathTex. Use `c2p` '
        "instead of `coords_to_point`. Use only these object methods: add, append, "
        "add_coordinates, "
        "align_to, animate, arrange, c2p, copy, get_axis_labels, get_bottom, get_center, "
        "get_end, get_graph_label, get_left, get_riemann_rectangles, get_right, get_start, "
        "get_top, get_value, move_to, mobjects, n2p, next_to, plot, play, remove, reverse, rotate, "
        "scale, set_color, "
        "set_fill, set_opacity, set_stroke, set_value, shift, to_edge, to_corner, wait. Do not add "
        "filesystem, network, process, reflection, or dynamic execution features. "
        "When the approved diagnostic reports a duration failure, replace the entire timeline: "
        "sum every explicit self.play run_time and self.wait value, keep each individual "
        "self.play run_time at or below 4 seconds, use active teaching animations rather than "
        "one long wait, and satisfy the exact target and accepted range stated below."
    )
    sections = [
        "CONTENT_PLAN_JSON:\n" + json.dumps(content_plan, ensure_ascii=False, sort_keys=True),
        "APPROVED_SANITIZED_DIAGNOSTIC:\n" + _sanitize_diagnostic(diagnostic),
        "REPAIR_METADATA_JSON:\n"
        + json.dumps(dict(decision.template_metadata), ensure_ascii=False, sort_keys=True),
    ]
    target = content_plan.get("target_duration_seconds")
    if isinstance(target, int | float) and not isinstance(target, bool) and target > 0:
        minimum_active_plays = math.ceil(target / 4)
        sections.insert(
            1,
            "TIMELINE_REPAIR_REQUIREMENT:\n"
            f"The replacement source must total exactly {target:g} seconds and remain within "
            f"{target * 0.9:.1f} to {target * 1.1:.1f} seconds. Count every explicit run_time "
            f"and wait value. Use at least {minimum_active_plays} active self.play calls because "
            "each play is limited to 4 seconds. Use enough short active animations to reach the "
            "target. Do not use one long wait or terminal padding.",
        )
    if decision.include_candidate_source:
        sections.append("PREVIOUS_CANDIDATE_SOURCE:\n" + candidate_source)
    return (
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(sections)},
    )


__all__ = [
    "CategoryPolicy",
    "CategoryPolicyState",
    "RepairAction",
    "RepairDecision",
    "RepairOrchestrator",
    "build_repair_messages",
]
