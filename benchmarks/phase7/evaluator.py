#!/usr/bin/env python3
"""Offline, redacted black-box evaluation for Phase 7.

This module never imports generated code, Docker, or a model provider.  Callers
inject a runner and security gate, allowing deterministic acceptance testing
without persisting prompts, generated source, diagnostics, or host paths.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

SUMMARY_RECORD_TYPE = "phase7-evaluation-summary-v1"
CASE_RECORD_TYPE = "phase7-evaluation-case-v1"
ATTACK_SUMMARY_RECORD_TYPE = "phase7-attack-summary-v1"
ATTACK_RECORD_TYPE = "phase7-attack-record-v1"
ATTACK_CORPUS_VERSION = "phase7-malicious-corpus-v1"
GOLD_SET_SIZE = 30
FIRST_RENDER_THRESHOLD = 0.75
FINAL_RENDER_THRESHOLD = 0.90
MATH_QUALITY_THRESHOLD = 0.90
VISUAL_QUALITY_THRESHOLD = 0.80
_CATEGORIES = frozenset({"formula_derivation", "function_visualization"})
_POLICY_STATES = frozenset({"active", "degraded", "paused"})
_ERROR_CODES = frozenset(
    {
        "invalid_model_response",
        "ast_parse_failed",
        "static_policy_repairable",
        "security_policy_violation",
        "compile_failed",
        "scene_structure_invalid",
        "render_failed",
        "sandbox_timeout",
        "sandbox_resource_limit",
        "internal_error",
    }
)

GoldCase = Mapping[str, object]
Runner = Callable[[GoldCase, int], object]
SecurityGate = Callable[[str], object]
SandboxProbe = Callable[[str], None]


class FailureInjection(str, Enum):
    """Deterministic, offline failures from the Phase 7 error taxonomy."""

    MODEL_RESPONSE = "model_response"
    AST_PARSE = "ast_parse"
    COMPILE = "compile"
    SCENE_STRUCTURE = "scene_structure"
    RENDER = "render"
    TIMEOUT = "timeout"
    RESOURCE_LIMIT = "resource_limit"


@dataclass(frozen=True, slots=True)
class RenderObservation:
    """A runner result whose sensitive fields are intentionally never serialized."""

    first_render_succeeded: bool
    final_render_succeeded: bool
    security_blocked: bool
    sandbox_invocations: int
    math_score: int | None
    visual_score: int | None
    attempts_used: int
    duration_ms: float
    error_code: str | None = None
    candidate_source: str | None = None
    diagnostic: str | None = None
    policy_state: str = "active"


@dataclass(frozen=True, slots=True)
class AttackCase:
    identifier: str
    vector: str
    source: str


@dataclass(frozen=True, slots=True)
class PerformanceAggregate:
    count: int
    mean_duration_ms: float
    p95_duration_ms: float
    max_duration_ms: float


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    case_sha256: str
    category: str
    first_render_succeeded: bool
    final_render_succeeded: bool
    math_score: int | None
    visual_score: int | None
    attempts_used: int
    error_code: str | None
    source_sha256: str
    policy_state: str
    reproducible: bool | None
    record_type: str = CASE_RECORD_TYPE

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Phase7EvaluationReport:
    records: tuple[EvaluationRecord, ...]
    repetitions: int
    performance: PerformanceAggregate

    @property
    def input_count(self) -> int:
        return len(self.records)

    @staticmethod
    def _rate(numerator: int, denominator: int) -> float:
        return numerator / denominator if denominator else 0.0

    @property
    def first_render_rate(self) -> float:
        successes = sum(record.first_render_succeeded for record in self.records)
        return self._rate(successes, self.input_count)

    @property
    def final_render_rate(self) -> float:
        successes = sum(record.final_render_succeeded for record in self.records)
        return self._rate(successes, self.input_count)

    @property
    def math_quality_rate(self) -> float:
        return self._rate(
            sum(
                record.math_score is not None and record.math_score >= 4
                for record in self.records
            ),
            self.input_count,
        )

    @property
    def visual_quality_rate(self) -> float:
        return self._rate(
            sum(
                record.visual_score is not None and record.visual_score >= 4
                for record in self.records
            ),
            self.input_count,
        )

    @property
    def reproducibility_rate(self) -> float | None:
        if self.repetitions < 3:
            return None
        reproducible = sum(record.reproducible is True for record in self.records)
        return self._rate(reproducible, self.input_count)

    @property
    def gate_failures(self) -> tuple[str, ...]:
        failures: list[str] = []
        if self.input_count != GOLD_SET_SIZE:
            failures.append("gold_set_size")
        if self.first_render_rate < FIRST_RENDER_THRESHOLD:
            failures.append("first_render_rate")
        if self.final_render_rate < FINAL_RENDER_THRESHOLD:
            failures.append("final_render_rate")
        if self.math_quality_rate < MATH_QUALITY_THRESHOLD:
            failures.append("math_quality_rate")
        if self.visual_quality_rate < VISUAL_QUALITY_THRESHOLD:
            failures.append("visual_quality_rate")
        return tuple(failures)

    @property
    def gates_passed(self) -> bool:
        """Gold-set gates; security corpus is evaluated separately and combined explicitly."""

        return not self.gate_failures

    def summary_dict(self) -> dict[str, object]:
        return {
            "record_type": SUMMARY_RECORD_TYPE,
            "input_count": self.input_count,
            "repetitions": self.repetitions,
            "gold_set_size_required": GOLD_SET_SIZE,
            "first_render_rate": self.first_render_rate,
            "final_render_rate": self.final_render_rate,
            "math_quality_rate": self.math_quality_rate,
            "visual_quality_rate": self.visual_quality_rate,
            "reproducibility_rate": self.reproducibility_rate,
            "performance": asdict(self.performance),
            "gate_failures": self.gate_failures,
            "gates_passed": self.gates_passed,
        }


@dataclass(frozen=True, slots=True)
class AttackRecord:
    attack_id: str
    vector: str
    blocked: bool
    sandbox_bypassed: bool
    record_type: str = ATTACK_RECORD_TYPE

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AttackCorpusReport:
    corpus_version: str
    records: tuple[AttackRecord, ...]

    @property
    def attack_count(self) -> int:
        return len(self.records)

    @property
    def sandbox_bypass_count(self) -> int:
        return sum(record.sandbox_bypassed for record in self.records)

    @property
    def security_block_rate(self) -> float:
        if not self.attack_count:
            return 0.0
        return sum(record.blocked for record in self.records) / self.attack_count

    @property
    def gates_passed(self) -> bool:
        return (
            self.attack_count > 0
            and self.security_block_rate == 1.0
            and self.sandbox_bypass_count == 0
        )

    def summary_dict(self) -> dict[str, object]:
        return {
            "record_type": ATTACK_SUMMARY_RECORD_TYPE,
            "corpus_version": self.corpus_version,
            "attack_count": self.attack_count,
            "security_block_rate": self.security_block_rate,
            "sandbox_bypass_count": self.sandbox_bypass_count,
            "gates_passed": self.gates_passed,
        }


class Phase7Evaluator:
    """Evaluate injected observations without executing or reporting unsafe input."""

    def __init__(self, *, runner: Runner) -> None:
        self._runner = runner

    @staticmethod
    def failure_injected_runner(runner: Runner, failure: FailureInjection) -> Runner:
        """Wrap a fake runner with a single deterministic failure, without I/O."""

        error_code = {
            FailureInjection.MODEL_RESPONSE: "invalid_model_response",
            FailureInjection.AST_PARSE: "ast_parse_failed",
            FailureInjection.COMPILE: "compile_failed",
            FailureInjection.SCENE_STRUCTURE: "scene_structure_invalid",
            FailureInjection.RENDER: "render_failed",
            FailureInjection.TIMEOUT: "sandbox_timeout",
            FailureInjection.RESOURCE_LIMIT: "sandbox_resource_limit",
        }[failure]

        def injected(case: GoldCase, repetition: int) -> RenderObservation:
            original = _as_observation(runner(case, repetition))
            return RenderObservation(
                first_render_succeeded=False,
                final_render_succeeded=False,
                security_blocked=failure is FailureInjection.AST_PARSE,
                sandbox_invocations=(
                    0 if failure is FailureInjection.AST_PARSE else original.sandbox_invocations
                ),
                math_score=None,
                visual_score=None,
                attempts_used=original.attempts_used,
                duration_ms=original.duration_ms,
                error_code=error_code,
                policy_state=original.policy_state,
            )

        return injected

    def evaluate(
        self, cases: Sequence[GoldCase], *, repetitions: int = 1
    ) -> Phase7EvaluationReport:
        if repetitions not in (1, 3):
            raise ValueError("repetitions must be 1 or 3")

        records: list[EvaluationRecord] = []
        durations: list[float] = []
        seen_identifiers: set[str] = set()
        for case in cases:
            identifier, category = _validate_case(case)
            if identifier in seen_identifiers:
                raise ValueError(f"duplicate gold case id: {identifier}")
            seen_identifiers.add(identifier)
            observations = tuple(
                _as_observation(self._runner(case, repetition))
                for repetition in range(1, repetitions + 1)
            )
            durations.extend(observation.duration_ms for observation in observations)
            primary = observations[0]
            fingerprints = {
                _reproducibility_fingerprint(observation) for observation in observations
            }
            records.append(
                EvaluationRecord(
                    case_sha256=_sha256(identifier),
                    category=category,
                    first_render_succeeded=primary.first_render_succeeded,
                    final_render_succeeded=primary.final_render_succeeded,
                    math_score=primary.math_score,
                    visual_score=primary.visual_score,
                    attempts_used=primary.attempts_used,
                    error_code=_safe_error_code(primary.error_code),
                    source_sha256=_sha256(primary.candidate_source or ""),
                    policy_state=_safe_policy_state(primary.policy_state),
                    reproducible=len(fingerprints) == 1 if repetitions == 3 else None,
                )
            )
        return Phase7EvaluationReport(
            records=tuple(records),
            repetitions=repetitions,
            performance=_performance(durations),
        )

    def evaluate_attacks(
        self,
        attacks: Sequence[AttackCase],
        *,
        security_gate: SecurityGate,
        sandbox_probe: SandboxProbe | None = None,
    ) -> AttackCorpusReport:
        records: list[AttackRecord] = []
        for attack in attacks:
            accepted = _security_gate_accepted(security_gate(attack.source))
            bypassed = accepted
            if bypassed and sandbox_probe is not None:
                sandbox_probe(attack.identifier)
            records.append(
                AttackRecord(
                    attack_id=attack.identifier,
                    vector=attack.vector,
                    blocked=not accepted,
                    sandbox_bypassed=bypassed,
                )
            )
        return AttackCorpusReport(corpus_version=ATTACK_CORPUS_VERSION, records=tuple(records))

    @staticmethod
    def combined_gates_passed(
        evaluation_report: Phase7EvaluationReport, attack_report: AttackCorpusReport
    ) -> bool:
        return evaluation_report.gates_passed and attack_report.gates_passed

    @staticmethod
    def write_jsonl_report(path: Path, report: Phase7EvaluationReport) -> None:
        _write_jsonl(
            path, [report.summary_dict(), *(record.as_dict() for record in report.records)]
        )

    @staticmethod
    def write_attack_jsonl_report(path: Path, report: AttackCorpusReport) -> None:
        _write_jsonl(
            path, [report.summary_dict(), *(record.as_dict() for record in report.records)]
        )


def load_attack_corpus(path: Path) -> tuple[AttackCase, ...]:
    """Load a versioned corpus while retaining source only in memory for the gate."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid attack corpus") from exc
    if not isinstance(payload, dict) or payload.get("version") != ATTACK_CORPUS_VERSION:
        raise ValueError("unsupported attack corpus version")
    raw_attacks = payload.get("attacks")
    if not isinstance(raw_attacks, list):
        raise ValueError("attack corpus requires an attacks list")
    attacks: list[AttackCase] = []
    identifiers: set[str] = set()
    for item in raw_attacks:
        if not isinstance(item, dict):
            raise ValueError("each attack must be an object")
        identifier, vector, source = item.get("id"), item.get("vector"), item.get("source")
        if not all(isinstance(value, str) and value for value in (identifier, vector, source)):
            raise ValueError("attack id, vector, and source must be nonempty strings")
        if identifier in identifiers:
            raise ValueError(f"duplicate attack id: {identifier}")
        identifiers.add(identifier)
        attacks.append(AttackCase(identifier=identifier, vector=vector, source=source))
    return tuple(attacks)


def _validate_case(case: GoldCase) -> tuple[str, str]:
    identifier, category = case.get("id"), case.get("category")
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("each gold case requires a nonempty id")
    if not isinstance(category, str) or category not in _CATEGORIES:
        raise ValueError("each gold case requires a supported category")
    return identifier, category


def _as_observation(value: object) -> RenderObservation:
    if isinstance(value, RenderObservation):
        _validate_observation(value)
        return value
    if not isinstance(value, Mapping):
        raise ValueError("runner must return RenderObservation or a mapping")
    try:
        observation = RenderObservation(
            first_render_succeeded=bool(value["first_render_succeeded"]),
            final_render_succeeded=bool(value["final_render_succeeded"]),
            security_blocked=bool(value.get("security_blocked", False)),
            sandbox_invocations=int(value.get("sandbox_invocations", 0)),
            math_score=(
                value.get("math_score") if isinstance(value.get("math_score"), int) else None
            ),
            visual_score=(
                value.get("visual_score") if isinstance(value.get("visual_score"), int) else None
            ),
            attempts_used=int(value["attempts_used"]),
            duration_ms=float(value["duration_ms"]),
            error_code=(
                value.get("error_code") if isinstance(value.get("error_code"), str) else None
            ),
            candidate_source=(
                value.get("candidate_source")
                if isinstance(value.get("candidate_source"), str)
                else None
            ),
            diagnostic=(
                value.get("diagnostic") if isinstance(value.get("diagnostic"), str) else None
            ),
            policy_state=(
                value.get("policy_state", "active")
                if isinstance(value.get("policy_state", "active"), str)
                else "unknown"
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid runner observation") from exc
    _validate_observation(observation)
    return observation


def _validate_observation(observation: RenderObservation) -> None:
    if not 0 <= observation.attempts_used <= 3:
        raise ValueError("attempts_used must be between 0 and 3")
    if observation.sandbox_invocations < 0:
        raise ValueError("sandbox_invocations must not be negative")
    if not math.isfinite(observation.duration_ms) or observation.duration_ms < 0:
        raise ValueError("duration_ms must be finite and nonnegative")
    for score in (observation.math_score, observation.visual_score):
        if score is not None and not 0 <= score <= 5:
            raise ValueError("quality scores must be between 0 and 5")


def _security_gate_accepted(verdict: object) -> bool:
    if isinstance(verdict, bool):
        return verdict
    if isinstance(verdict, Mapping):
        allowed = verdict.get("allowed")
        return allowed is True
    allowed = getattr(verdict, "allowed", None)
    return allowed is True


def _safe_error_code(error_code: str | None) -> str | None:
    return error_code if error_code in _ERROR_CODES else ("internal_error" if error_code else None)


def _safe_policy_state(policy_state: str) -> str:
    return policy_state if policy_state in _POLICY_STATES else "unknown"


def _reproducibility_fingerprint(observation: RenderObservation) -> str:
    return _sha256(
        json.dumps(
            {
                "source_sha256": _sha256(observation.candidate_source or ""),
                "attempts_used": observation.attempts_used,
                "error_code": _safe_error_code(observation.error_code),
                "policy_state": _safe_policy_state(observation.policy_state),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _performance(durations: Sequence[float]) -> PerformanceAggregate:
    if not durations:
        return PerformanceAggregate(
            count=0, mean_duration_ms=0.0, p95_duration_ms=0.0, max_duration_ms=0.0
        )
    ordered = sorted(durations)
    position = (len(ordered) - 1) * 0.95
    lower, upper = math.floor(position), math.ceil(position)
    percentile = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return PerformanceAggregate(
        count=len(ordered),
        mean_duration_ms=sum(ordered) / len(ordered),
        p95_duration_ms=percentile,
        max_duration_ms=ordered[-1],
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_jsonl(path: Path, records: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
