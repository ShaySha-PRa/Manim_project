#!/usr/bin/env python3
"""Offline, dependency-injected evaluation for Phase 6 ContentPlan generation.

This module deliberately has no Provider configuration and never serializes raw
model text.  A caller supplies a generator (normally a fake in tests) and may
inject the production semantic/formula validators after they are available.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from manim_workbench_contracts import ContentPlanModelResponse, ContentPlanOutcome
from pydantic import ValidationError

SUMMARY_RECORD_TYPE = "phase6-evaluation-summary-v1"
PROMPT_RECORD_TYPE = "phase6-evaluation-prompt-v1"
GOLD_SET_SIZE = 30
SCHEMA_REQUIRED_COUNT = 29
SEMANTIC_REQUIRED_COUNT = 27
FORMULA_REQUIRED_COUNT = 29
_ACTIONABLE_ERROR_CODES = frozenset(
    {
        "configuration_error",
        "provider_auth_error",
        "provider_rate_limited",
        "provider_unavailable",
        "provider_empty_response",
        "provider_truncated_response",
        "provider_invalid_json",
        "provider_schema_error",
        "content_plan_semantic_error",
        "prompt_version_not_found",
        "ownership_mismatch",
    }
)
_UNSAFE_FORMULA_MARKERS = ("```", "<script", "</script", "<html", "$(", "import ", "shell")

GoldEntry = Mapping[str, Any]
Generator = Callable[[GoldEntry, int], object]
SemanticValidator = Callable[[ContentPlanModelResponse], object]
FormulaParser = Callable[[str], bool]


class FailureInjection(str, Enum):
    """Offline failures required by the Phase 6 threat model."""

    EMPTY = "empty"
    TRUNCATED = "truncated"
    INVALID_JSON = "invalid_json"
    SCHEMA = "schema"
    SEMANTIC = "semantic"


@dataclass(frozen=True, slots=True)
class GenerationOutput:
    """Minimal, provider-neutral observation; never written to a report."""

    content: str | None
    finish_reason: str | None = None
    error_code: str | None = None
    injected_failure: FailureInjection | None = None


@dataclass(frozen=True, slots=True)
class PromptEvaluation:
    prompt_id: str
    category: str
    outcome: str | None
    schema_valid: bool
    semantic_valid: bool
    formula_parse_success: bool | None
    actionable_outcome: bool
    error_code: str | None
    structure_stable: bool | None
    structure_signature_sha256: str
    record_type: str = PROMPT_RECORD_TYPE

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Phase6EvaluationReport:
    records: tuple[PromptEvaluation, ...]
    repetitions: int

    @property
    def input_count(self) -> int:
        return len(self.records)

    @property
    def schema_valid_count(self) -> int:
        return sum(record.schema_valid for record in self.records)

    @property
    def semantic_valid_count(self) -> int:
        return sum(record.semantic_valid for record in self.records)

    @property
    def schema_required_count(self) -> int:
        return SCHEMA_REQUIRED_COUNT

    @property
    def semantic_required_count(self) -> int:
        return SEMANTIC_REQUIRED_COUNT

    @property
    def formula_required_count(self) -> int:
        return FORMULA_REQUIRED_COUNT

    @property
    def formula_evaluated_count(self) -> int:
        return sum(record.formula_parse_success is not None for record in self.records)

    @property
    def formula_parse_success_count(self) -> int:
        return sum(record.formula_parse_success is True for record in self.records)

    @property
    def actionable_outcome_count(self) -> int:
        return sum(record.actionable_outcome for record in self.records)

    @property
    def structure_stability_count(self) -> int:
        return sum(record.structure_stable is True for record in self.records)

    @staticmethod
    def _rate(numerator: int, denominator: int) -> float:
        return numerator / denominator if denominator else 0.0

    @property
    def schema_valid_rate(self) -> float:
        return self._rate(self.schema_valid_count, self.input_count)

    @property
    def semantic_valid_rate(self) -> float:
        return self._rate(self.semantic_valid_count, self.input_count)

    @property
    def formula_parse_success_rate(self) -> float:
        return self._rate(self.formula_parse_success_count, self.input_count)

    @property
    def actionable_outcome_rate(self) -> float:
        return self._rate(self.actionable_outcome_count, self.input_count)

    @property
    def structure_stability_rate(self) -> float | None:
        if self.repetitions < 3:
            return None
        return self._rate(self.structure_stability_count, self.input_count)

    @property
    def gates_passed(self) -> bool:
        """Apply the frozen Phase 6 thresholds to exactly 30 gold prompts."""

        return (
            self.input_count == GOLD_SET_SIZE
            and self.schema_valid_count >= SCHEMA_REQUIRED_COUNT
            and self.semantic_valid_count >= SEMANTIC_REQUIRED_COUNT
            and self.formula_parse_success_count >= FORMULA_REQUIRED_COUNT
            and self.actionable_outcome_count == GOLD_SET_SIZE
        )

    def summary_dict(self) -> dict[str, object]:
        return {
            "record_type": SUMMARY_RECORD_TYPE,
            "input_count": self.input_count,
            "repetitions": self.repetitions,
            "gold_set_size_required": GOLD_SET_SIZE,
            "schema_required_count": self.schema_required_count,
            "schema_valid_count": self.schema_valid_count,
            "schema_valid_rate": self.schema_valid_rate,
            "semantic_required_count": self.semantic_required_count,
            "semantic_valid_count": self.semantic_valid_count,
            "semantic_valid_rate": self.semantic_valid_rate,
            "formula_evaluated_count": self.formula_evaluated_count,
            "formula_required_count": self.formula_required_count,
            "formula_parse_success_count": self.formula_parse_success_count,
            "formula_parse_success_rate": self.formula_parse_success_rate,
            "actionable_outcome_count": self.actionable_outcome_count,
            "actionable_outcome_rate": self.actionable_outcome_rate,
            "structure_stability_count": self.structure_stability_count,
            "structure_stability_rate": self.structure_stability_rate,
            "gates_passed": self.gates_passed,
        }


@dataclass(frozen=True, slots=True)
class _EvaluatedAttempt:
    schema_valid: bool
    semantic_valid: bool
    formula_parse_success: bool | None
    actionable_outcome: bool
    error_code: str | None
    outcome: str | None
    structure_signature_sha256: str


def load_gold_prompts(path: Path) -> tuple[dict[str, Any], ...]:
    """Read JSONL without transforming or writing the versioned gold set."""

    entries: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid gold JSON at line {line_number}") from exc
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                raise ValueError(f"gold entry at line {line_number} must be an object with an id")
            if entry["id"] in identifiers:
                raise ValueError(f"duplicate gold entry id: {entry['id']}")
            identifiers.add(entry["id"])
            entries.append(entry)
    return tuple(entries)


class Phase6Evaluator:
    """Evaluate untrusted generation observations without storing their content."""

    def __init__(
        self,
        *,
        generator: Generator,
        semantic_validator: SemanticValidator | None = None,
        formula_parser: FormulaParser | None = None,
    ) -> None:
        self._generator = generator
        self._semantic_validator = semantic_validator or (lambda _response: True)
        self._formula_parser = formula_parser or _default_formula_parser

    @staticmethod
    def failure_injected_generator(generator: Generator, failure: FailureInjection) -> Generator:
        """Wrap a fake generator with one deterministic, offline failure mode."""

        def generate(entry: GoldEntry, attempt: int) -> object:
            if failure is FailureInjection.EMPTY:
                return GenerationOutput(content=None)
            if failure is FailureInjection.TRUNCATED:
                return GenerationOutput(content='{"outcome":', finish_reason="length")
            if failure is FailureInjection.INVALID_JSON:
                return GenerationOutput(content="{not-json")
            if failure is FailureInjection.SCHEMA:
                return GenerationOutput(content='{"outcome":"ready"}')
            original = _as_generation_output(generator(entry, attempt))
            return GenerationOutput(
                content=original.content,
                finish_reason=original.finish_reason,
                error_code=original.error_code,
                injected_failure=FailureInjection.SEMANTIC,
            )

        return generate

    def evaluate(
        self, entries: Sequence[GoldEntry], *, repetitions: int = 1
    ) -> Phase6EvaluationReport:
        if repetitions < 1:
            raise ValueError("repetitions must be at least one")

        records: list[PromptEvaluation] = []
        for entry in entries:
            prompt_id = entry.get("id")
            category = entry.get("category")
            if not isinstance(prompt_id, str) or not isinstance(category, str):
                raise ValueError("each gold entry requires string id and category")
            attempts = tuple(
                self._evaluate_attempt(_as_generation_output(self._generator(entry, number)))
                for number in range(1, repetitions + 1)
            )
            primary = attempts[0]
            signatures = {attempt.structure_signature_sha256 for attempt in attempts}
            records.append(
                PromptEvaluation(
                    prompt_id=prompt_id,
                    category=category,
                    outcome=primary.outcome,
                    schema_valid=primary.schema_valid,
                    semantic_valid=primary.semantic_valid,
                    formula_parse_success=primary.formula_parse_success,
                    actionable_outcome=primary.actionable_outcome,
                    error_code=primary.error_code,
                    structure_stable=(len(signatures) == 1 if repetitions >= 3 else None),
                    structure_signature_sha256=primary.structure_signature_sha256,
                )
            )
        return Phase6EvaluationReport(records=tuple(records), repetitions=repetitions)

    def write_jsonl_report(self, path: Path, report: Phase6EvaluationReport) -> None:
        """Create a redacted JSONL artifact and fail rather than overwrite evidence."""

        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(report.summary_dict(), ensure_ascii=False, sort_keys=True)]
        lines.extend(
            json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True)
            for record in report.records
        )
        with path.open("x", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    def _evaluate_attempt(self, output: GenerationOutput) -> _EvaluatedAttempt:
        if output.error_code in _ACTIONABLE_ERROR_CODES:
            return self._failure_attempt(output.error_code)
        if output.content is None or not output.content.strip():
            return self._failure_attempt("provider_empty_response")
        if output.finish_reason == "length":
            return self._failure_attempt("provider_truncated_response")
        try:
            payload = json.loads(output.content)
        except json.JSONDecodeError:
            return self._failure_attempt("provider_invalid_json")
        if not isinstance(payload, dict):
            return self._failure_attempt("provider_schema_error")
        try:
            response = ContentPlanModelResponse.model_validate(payload)
        except ValidationError:
            return self._failure_attempt("provider_schema_error")

        semantic_valid = self._semantic_valid(response, output.injected_failure)
        formula_parse_success = self._formula_parse_success(response)
        error_code = None if semantic_valid else "content_plan_semantic_error"
        return _EvaluatedAttempt(
            schema_valid=True,
            semantic_valid=semantic_valid,
            formula_parse_success=formula_parse_success,
            actionable_outcome=True,
            error_code=error_code,
            outcome=response.outcome.value,
            structure_signature_sha256=_shape_digest(payload),
        )

    @staticmethod
    def _failure_attempt(error_code: str) -> _EvaluatedAttempt:
        return _EvaluatedAttempt(
            schema_valid=False,
            semantic_valid=False,
            formula_parse_success=None,
            actionable_outcome=error_code in _ACTIONABLE_ERROR_CODES,
            error_code=error_code,
            outcome=None,
            structure_signature_sha256=_shape_digest({"failure": error_code}),
        )

    def _semantic_valid(
        self, response: ContentPlanModelResponse, injected_failure: FailureInjection | None
    ) -> bool:
        if injected_failure is FailureInjection.SEMANTIC:
            return False
        try:
            verdict = self._semantic_validator(response)
        except Exception:
            return False
        return verdict is not False

    def _formula_parse_success(self, response: ContentPlanModelResponse) -> bool | None:
        if response.outcome is not ContentPlanOutcome.READY or response.plan is None:
            return None
        return all(
            self._formula_parser(step.expression)
            for scene in response.plan.scenes
            for step in scene.formula_steps
        )


def _as_generation_output(value: object) -> GenerationOutput:
    if isinstance(value, GenerationOutput):
        return value
    if isinstance(value, str):
        return GenerationOutput(content=value)
    if value is None:
        return GenerationOutput(content=None)
    if isinstance(value, Mapping):
        content = value.get("content")
        finish_reason = value.get("finish_reason")
        error_code = value.get("error_code")
        if (
            (content is not None and not isinstance(content, str))
            or (finish_reason is not None and not isinstance(finish_reason, str))
            or (error_code is not None and not isinstance(error_code, str))
        ):
            return GenerationOutput(content=None, error_code="provider_schema_error")
        return GenerationOutput(content=content, finish_reason=finish_reason, error_code=error_code)
    return GenerationOutput(content=None, error_code="provider_schema_error")


def _default_formula_parser(expression: str) -> bool:
    normalized = expression.strip().lower()
    if not normalized or any(marker in normalized for marker in _UNSAFE_FORMULA_MARKERS):
        return False
    stack: list[str] = []
    closing = {")": "(", "]": "[", "}": "{"}
    for character in normalized:
        if character in "([{":
            stack.append(character)
        elif character in closing:
            if not stack or stack.pop() != closing[character]:
                return False
    return not stack


def _shape_digest(payload: object) -> str:
    encoded = json.dumps(
        _shape_of(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _shape_of(value: object) -> object:
    if isinstance(value, dict):
        return {key: _shape_of(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return {"list_length": len(value), "item_shapes": [_shape_of(item) for item in value]}
    if value is None:
        return "null"
    return type(value).__name__


def _fixture_generator(path: Path) -> Generator:
    fixtures = load_gold_prompts(path)
    by_id = {entry["id"]: entry for entry in fixtures}

    def generate(entry: GoldEntry, _attempt: int) -> object:
        fixture = by_id.get(entry["id"])
        if fixture is None:
            return GenerationOutput(content=None, error_code="provider_unavailable")
        content = fixture.get("content")
        finish_reason = fixture.get("finish_reason")
        error_code = fixture.get("error_code")
        return GenerationOutput(
            content=content if isinstance(content, str) else None,
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
            error_code=error_code if isinstance(error_code, str) else None,
        )

    return generate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a redacted offline Phase 6 JSONL evaluation."
    )
    parser.add_argument("--gold-set", required=True, type=Path)
    parser.add_argument(
        "--fixture", required=True, type=Path, help="Offline JSONL fake-generation fixture."
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repetitions", type=int, default=1, choices=(1, 3))
    arguments = parser.parse_args(argv)

    report = Phase6Evaluator(generator=_fixture_generator(arguments.fixture)).evaluate(
        load_gold_prompts(arguments.gold_set), repetitions=arguments.repetitions
    )
    report_writer = Phase6Evaluator(generator=lambda _entry, _attempt: None)
    report_writer.write_jsonl_report(arguments.output, report)
    print(json.dumps(report.summary_dict(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
