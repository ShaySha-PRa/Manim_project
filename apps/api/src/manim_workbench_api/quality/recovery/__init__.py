"""Deterministic, bounded Phase 9 quality-recovery policy.

The module is intentionally pure: it does not invoke a provider, read source
code, inspect artifacts, or persist state.  The parent orchestration layer owns
those boundaries and must re-run all Phase 7 checks after a repair.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final

_MAX_REPAIRS: Final = 2
_PAYLOAD_TEMPLATE_VERSION: Final = "phase9-quality-repair-v1"
_SIGNATURE: Final = re.compile(r"^[0-9a-f]{64}$")
_MAX_METRIC_VALUE: Final = 3_600.0


class QualityRecoveryAction(str, Enum):
    """Parent-facing next state; this policy never performs the action itself."""

    REPAIR = "repair"
    DEGRADED = "degraded"
    FAILED = "failed"


class RecoveryFailureReason(str, Enum):
    """Stable, redacted explanations suitable for report and API adaptation."""

    SECURITY_POLICY = "security_policy"
    INFRASTRUCTURE = "infrastructure"
    REPEATED_SIGNATURE = "repeated_signature"
    REPAIR_BUDGET_EXHAUSTED = "repair_budget_exhausted"
    NON_REPAIRABLE = "non_repairable"


@dataclass(frozen=True, slots=True)
class AllowedDiagnosticFact:
    """The only diagnostic data that may enter a model-facing repair payload."""

    code: str
    measured_value: float | None
    threshold_value: float | None


@dataclass(frozen=True, slots=True)
class QualityRepairPayload:
    """Categorized, source-free instructions for a future Phase 7 repair call."""

    categories: tuple[str, ...]
    facts: tuple[AllowedDiagnosticFact, ...]
    instructions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QualityRecoveryDecision:
    """A deterministic decision with no raw diagnostic, source, or log content."""

    action: QualityRecoveryAction
    next_repair_count: int
    diagnostic_signature: str
    user_suggestion: str
    failure_reason: RecoveryFailureReason | None = None
    repair_payload: QualityRepairPayload | None = None


@dataclass(frozen=True, slots=True)
class _NormalizedDiagnostic:
    code: str
    severity: str
    fact: AllowedDiagnosticFact


_SECURITY_CODES: Final = frozenset({"source_not_approved"})
_INFRASTRUCTURE_CODES: Final = frozenset(
    {
        "media_metadata_invalid",
        "media_metadata_inconsistent",
        "preview_final_timeline_mismatch",
    }
)
_REPAIRABLE_CODES: Final = frozenset(
    {
        "default_play_duration_assumed",
        "duration_too_short",
        "duration_too_long",
        "long_static_segment",
        "terminal_wait_padding",
        "blank_frame",
        "object_out_of_bounds",
        "object_overlap",
        "text_too_small",
        "cjk_glyph_missing",
        "key_formula_missing",
        "object_missing",
        "animation_order_mismatch",
        "timeline_unknown",
        "planned_scene_missing",
    }
)
_DEGRADABLE_WARNING_CODES: Final = frozenset({"object_overlap", "text_too_small"})

_INSTRUCTIONS: Final = MappingProxyType(
    {
        "default_play_duration_assumed": (
            "Use explicit finite run_time values for each teaching animation."
        ),
        "duration_too_short": (
            "Add meaningful explanatory animation across planned scenes; do not add idle waits."
        ),
        "duration_too_long": (
            "Shorten redundant instructional beats while retaining planned formulas and objects."
        ),
        "long_static_segment": "Replace long static holds with progressive explanatory animation.",
        "terminal_wait_padding": (
            "Remove terminal padding and distribute time across teaching beats."
        ),
        "blank_frame": (
            "Ensure planned scenes keep visible instructional objects during their active interval."
        ),
        "object_out_of_bounds": (
            "Keep every instructional object inside the visible frame with a readable margin."
        ),
        "object_overlap": "Separate instructional objects so labels and formulas remain readable.",
        "text_too_small": "Increase instructional text size and preserve readable spacing.",
        "cjk_glyph_missing": (
            "Use the approved CJK-safe text treatment for all Chinese instructional text."
        ),
        "key_formula_missing": "Restore every planned key formula in its intended teaching step.",
        "object_missing": "Restore every planned instructional object before rendering.",
        "animation_order_mismatch": (
            "Restore the planned animation order for the teaching sequence."
        ),
        "timeline_unknown": (
            "Use statically analyzable explicit play and wait durations; avoid dynamic values."
        ),
        "planned_scene_missing": "Restore the missing planned teaching scene and objective.",
    }
)
_SUGGESTIONS: Final = MappingProxyType(
    {
        "default_play_duration_assumed": (
            "Make animation durations explicit so the video duration can be verified."
        ),
        "duration_too_short": (
            "Add explanation to planned teaching steps instead of adding a static ending."
        ),
        "duration_too_long": (
            "Shorten redundant animation while keeping the planned explanation intact."
        ),
        "long_static_segment": (
            "Replace the long static segment with a meaningful explanatory animation."
        ),
        "terminal_wait_padding": "Move ending hold time into explanatory teaching steps.",
        "blank_frame": "Add visible instructional content to the affected scene.",
        "object_out_of_bounds": "Move the affected object into the visible teaching area.",
        "object_overlap": "Increase spacing between overlapping instructional objects.",
        "text_too_small": "Increase the size of small instructional text.",
        "cjk_glyph_missing": "Use a CJK-capable text treatment for Chinese instructional content.",
        "key_formula_missing": "Restore the planned key formula.",
        "object_missing": "Restore the planned instructional object.",
        "animation_order_mismatch": "Restore the planned animation order.",
        "timeline_unknown": (
            "Use explicit, fixed animation durations so the timeline can be checked."
        ),
        "planned_scene_missing": "Restore the missing teaching scene.",
    }
)


class QualityRecoveryPolicy:
    """Choose one bounded repair, degradation, or failure outcome.

    The caller supplies the append-only report's current and historical
    diagnostic signatures.  A repeated signature stops recovery before any
    model request.  No field from a raw error is accepted or retained.
    """

    def decide(
        self,
        *,
        diagnostics: Iterable[Mapping[str, object] | object],
        repair_count: int,
        diagnostic_signature: str,
        prior_diagnostic_signatures: Iterable[str],
    ) -> QualityRecoveryDecision:
        signature = _validated_signature(diagnostic_signature)
        prior = frozenset(_validated_signature(item) for item in prior_diagnostic_signatures)
        if not isinstance(repair_count, int) or isinstance(repair_count, bool):
            raise ValueError("repair_count must be an integer in the inclusive range 0..2")
        if not 0 <= repair_count <= _MAX_REPAIRS:
            raise ValueError("repair_count must be an integer in the inclusive range 0..2")

        normalized = _normalized_diagnostics(diagnostics)
        if normalized is None:
            return self._failed(
                signature,
                repair_count,
                RecoveryFailureReason.NON_REPAIRABLE,
                "The quality result cannot be repaired automatically. Review the affected pipeline "
                "stage.",
            )
        codes = frozenset(item.code for item in normalized)
        known_codes = _REPAIRABLE_CODES | _SECURITY_CODES | _INFRASTRUCTURE_CODES
        if not normalized or any(item.code not in known_codes for item in normalized):
            return self._failed(
                signature,
                repair_count,
                RecoveryFailureReason.NON_REPAIRABLE,
                "The quality result cannot be repaired automatically. Review the affected pipeline "
                "stage.",
            )
        if codes & _SECURITY_CODES:
            return self._failed(
                signature,
                repair_count,
                RecoveryFailureReason.SECURITY_POLICY,
                "The candidate did not pass the required security policy and was not sent for "
                "repair.",
            )
        if codes & _INFRASTRUCTURE_CODES:
            return self._failed(
                signature,
                repair_count,
                RecoveryFailureReason.INFRASTRUCTURE,
                "Rendering evidence could not be verified. Retry the affected render pipeline "
                "stage.",
            )
        if signature in prior:
            return self._terminal_after_stop(
                normalized,
                signature,
                repair_count,
                RecoveryFailureReason.REPEATED_SIGNATURE,
            )
        if repair_count == _MAX_REPAIRS:
            return self._terminal_after_stop(
                normalized,
                signature,
                repair_count,
                RecoveryFailureReason.REPAIR_BUDGET_EXHAUSTED,
            )

        payload = _payload(normalized)
        return QualityRecoveryDecision(
            action=QualityRecoveryAction.REPAIR,
            next_repair_count=repair_count + 1,
            diagnostic_signature=signature,
            user_suggestion=_suggestion_for(normalized),
            repair_payload=payload,
        )

    @staticmethod
    def _failed(
        signature: str,
        repair_count: int,
        reason: RecoveryFailureReason,
        suggestion: str,
    ) -> QualityRecoveryDecision:
        return QualityRecoveryDecision(
            action=QualityRecoveryAction.FAILED,
            next_repair_count=repair_count,
            diagnostic_signature=signature,
            user_suggestion=suggestion,
            failure_reason=reason,
        )

    def _terminal_after_stop(
        self,
        diagnostics: tuple[_NormalizedDiagnostic, ...],
        signature: str,
        repair_count: int,
        reason: RecoveryFailureReason,
    ) -> QualityRecoveryDecision:
        if _only_degradable_warnings(diagnostics):
            return QualityRecoveryDecision(
                action=QualityRecoveryAction.DEGRADED,
                next_repair_count=repair_count,
                diagnostic_signature=signature,
                user_suggestion=_suggestion_for(diagnostics),
                failure_reason=reason,
            )
        return self._failed(
            signature,
            repair_count,
            reason,
            _suggestion_for(diagnostics),
        )


def build_quality_repair_payload(decision: QualityRecoveryDecision) -> dict[str, object]:
    """Return the exact, allowlisted model payload for a repair decision.

    It has no source code, user prompt, artifact path, secret, or raw diagnostic
    log.  Parent integration may pass it to Phase 7 only after enforcing that
    module's own source, AST, sandbox, and provider boundaries.
    """

    if decision.action is not QualityRecoveryAction.REPAIR or decision.repair_payload is None:
        raise ValueError("only a quality repair decision can build a repair payload")
    payload = decision.repair_payload
    return {
        "template_version": _PAYLOAD_TEMPLATE_VERSION,
        "categories": list(payload.categories),
        "facts": [
            {
                "code": fact.code,
                "measured_value": fact.measured_value,
                "threshold_value": fact.threshold_value,
            }
            for fact in payload.facts
        ],
        "instructions": list(payload.instructions),
    }


def _normalized_diagnostics(
    diagnostics: Iterable[Mapping[str, object] | object],
) -> tuple[_NormalizedDiagnostic, ...] | None:
    normalized: list[_NormalizedDiagnostic] = []
    for diagnostic in diagnostics:
        code = _enum_value(_field(diagnostic, "code"))
        severity = _enum_value(_field(diagnostic, "severity"))
        if not isinstance(code, str) or not isinstance(severity, str):
            return None
        if severity not in {"info", "warning", "error"}:
            return None
        measured = _metric(_field(diagnostic, "measured_value"))
        threshold = _metric(_field(diagnostic, "threshold_value"))
        if measured is _InvalidMetric or threshold is _InvalidMetric:
            return None
        normalized.append(
            _NormalizedDiagnostic(
                code=code,
                severity=severity,
                fact=AllowedDiagnosticFact(
                    code=code,
                    measured_value=measured,
                    threshold_value=threshold,
                ),
            )
        )
    return tuple(sorted(set(normalized), key=_diagnostic_sort_key))


class _InvalidMetricType:
    pass


_InvalidMetric: Final = _InvalidMetricType()


def _metric(value: object) -> float | None | _InvalidMetricType:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return _InvalidMetric
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= _MAX_METRIC_VALUE:
        return _InvalidMetric
    return number


def _field(diagnostic: Mapping[str, object] | object, field: str) -> object:
    if isinstance(diagnostic, Mapping):
        return diagnostic.get(field)
    return getattr(diagnostic, field, None)


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def _validated_signature(value: str) -> str:
    if not isinstance(value, str) or _SIGNATURE.fullmatch(value) is None:
        raise ValueError("diagnostic_signature must be a lowercase SHA-256 hex digest")
    return value


def _diagnostic_sort_key(item: _NormalizedDiagnostic) -> tuple[str, str, float, float]:
    return (
        item.code,
        item.severity,
        _metric_sort_value(item.fact.measured_value),
        _metric_sort_value(item.fact.threshold_value),
    )


def _fact_sort_key(item: AllowedDiagnosticFact) -> tuple[str, float, float]:
    return (
        item.code,
        _metric_sort_value(item.measured_value),
        _metric_sort_value(item.threshold_value),
    )


def _metric_sort_value(value: float | None) -> float:
    return -1.0 if value is None else value


def _payload(diagnostics: tuple[_NormalizedDiagnostic, ...]) -> QualityRepairPayload:
    categories = tuple(sorted({item.code for item in diagnostics}))
    facts = tuple(sorted({item.fact for item in diagnostics}, key=_fact_sort_key))
    return QualityRepairPayload(
        categories=categories,
        facts=facts,
        instructions=tuple(_INSTRUCTIONS[code] for code in categories),
    )


def _only_degradable_warnings(diagnostics: tuple[_NormalizedDiagnostic, ...]) -> bool:
    return bool(diagnostics) and all(
        item.severity == "warning" and item.code in _DEGRADABLE_WARNING_CODES
        for item in diagnostics
    )


def _suggestion_for(diagnostics: tuple[_NormalizedDiagnostic, ...]) -> str:
    suggestions = sorted({_SUGGESTIONS[item.code] for item in diagnostics})
    return " ".join(suggestions)


__all__ = [
    "AllowedDiagnosticFact",
    "QualityRecoveryAction",
    "QualityRecoveryDecision",
    "QualityRecoveryPolicy",
    "QualityRepairPayload",
    "RecoveryFailureReason",
    "build_quality_repair_payload",
]
