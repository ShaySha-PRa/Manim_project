"""Bounded, offline Phase 9 quality acceptance gate.

The gate deliberately consumes terminal-record summaries instead of importing
production services.  That keeps the oracle independent: real pipelines can
export the same redacted record shape without giving this harness access to
source, prompts, credentials, filesystem paths, or tenant identifiers.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

MAX_INPUT_BYTES = 1_000_000
PROFILES = frozenset({"preview", "final"})
TERMINAL_STATUSES = frozenset({"passed", "degraded", "failed"})
VALID_CATEGORIES = frozenset({"formula_derivation", "function_visualization"})
SEVERE_CODES = frozenset(
    {
        "duration_too_short",
        "duration_too_long",
        "long_static_segment",
        "terminal_wait_padding",
        "blank_frame",
        "object_out_of_bounds",
        "cjk_glyph_missing",
        "key_formula_missing",
        "object_missing",
    }
)
SECRET_OR_ABSOLUTE_VALUE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{6,}|(?:^|[\\s])[A-Za-z]:[\\/]|(?:^|[\\s])/(?:[^\\s]+))",
    re.IGNORECASE,
)


class AcceptanceFailure(ValueError):
    """Stable, redacted failure for an independent acceptance violation."""


def load_corpus(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    _reject_sensitive_values(payload)
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise AcceptanceFailure("invalid_corpus_schema")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != 30:
        raise AcceptanceFailure("invalid_golden_case_count")
    identifiers: set[str] = set()
    for case in cases:
        _validate_case(case, identifiers)
    return payload


def load_metrics_baseline(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    _reject_sensitive_values(payload)
    if not isinstance(payload, dict):
        raise AcceptanceFailure("invalid_metrics_baseline")
    metrics = payload.get("minimum_metrics")
    if payload.get("schema_version") != "1.0" or not isinstance(metrics, dict):
        raise AcceptanceFailure("invalid_metrics_baseline")
    if not metrics or any(not isinstance(value, int | float) for value in metrics.values()):
        raise AcceptanceFailure("invalid_metrics_baseline")
    return payload


def load_terminal_records(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path)
    _reject_sensitive_values(payload)
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list) or not all(isinstance(record, Mapping) for record in records):
        raise AcceptanceFailure("invalid_terminal_records")
    return [dict(record) for record in records]


def build_terminal_records(corpus: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Construct deterministic, redacted Preview/Final record fixtures from the corpus."""
    cases = corpus.get("cases")
    if not isinstance(cases, Sequence):
        raise AcceptanceFailure("invalid_corpus_schema")
    records: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, Mapping):
            raise AcceptanceFailure("invalid_golden_case")
        for profile in ("preview", "final"):
            frame_key = "preview_frame_count" if profile == "preview" else "final_frame_count"
            frame_count = case[frame_key]
            signature = _signature(case["id"], profile, case["diagnostic_codes"])
            records.append(
                {
                    "case_id": case["id"],
                    "profile": profile,
                    "terminal_status": case["terminal_status"],
                    "target_duration_seconds": case["target_duration_seconds"],
                    "estimated_duration_seconds": case["estimated_duration_seconds"],
                    "actual_duration_seconds": case["actual_duration_seconds"],
                    "frame_rate": case["frame_rate"],
                    "frame_count": frame_count,
                    "longest_static_seconds": case["longest_static_seconds"],
                    "repair_count": case["repair_count"],
                    "diagnostic_codes": list(case["diagnostic_codes"]),
                    "required_diagnostic_codes": list(case["diagnostic_codes"]),
                    "diagnostic_signature": signature,
                    "replay_signature": signature,
                    "repeated_signature": case["repeated_signature"],
                    "cross_owner_access": "denied",
                    "analysis_elapsed_ms": case["analysis_elapsed_ms"],
                    "provenance_version": case["provenance_version"],
                }
            )
    return records


def evaluate_acceptance(
    *,
    corpus: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    """Fail closed when a terminal record bypasses a Phase 9 quality invariant."""
    cases = corpus.get("cases")
    if not isinstance(cases, Sequence):
        raise AcceptanceFailure("invalid_corpus_schema")
    case_by_id = {case["id"]: case for case in cases if isinstance(case, Mapping)}
    normalized = [dict(record) for record in records]
    _reject_sensitive_values(normalized)
    expected_pairs = {(case_id, profile) for case_id in case_by_id for profile in PROFILES}
    actual_pairs = {(record.get("case_id"), record.get("profile")) for record in normalized}
    if len(normalized) != 60 or actual_pairs != expected_pairs:
        raise AcceptanceFailure("terminal_record_set_incomplete")

    records_by_case: dict[str, dict[str, dict[str, Any]]] = {}
    for record in normalized:
        case_id = record.get("case_id")
        profile = record.get("profile")
        if not isinstance(case_id, str) or profile not in PROFILES:
            raise AcceptanceFailure("invalid_terminal_record")
        records_by_case.setdefault(case_id, {})[profile] = record
        _validate_terminal_record(record, case_by_id[case_id]["terminal_status"])

    for pair in records_by_case.values():
        _validate_pair(pair["preview"], pair["final"])

    metrics = _metrics(normalized, records_by_case)
    _assert_metric_baseline(metrics, baseline)
    return {
        "schema_version": "1.0",
        "status": "passed",
        "metrics": metrics,
        "cases": {"evaluated": len(case_by_id), "failed": 0},
    }


def _read_json(path: Path) -> Any:
    try:
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise AcceptanceFailure("input_size_limit")
        return json.loads(path.read_text(encoding="utf-8"))
    except AcceptanceFailure:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise AcceptanceFailure("invalid_acceptance_input") from None


def _validate_case(case: object, identifiers: set[str]) -> None:
    if not isinstance(case, Mapping):
        raise AcceptanceFailure("invalid_golden_case")
    required = {
        "id",
        "category",
        "coverage",
        "terminal_status",
        "target_duration_seconds",
        "estimated_duration_seconds",
        "actual_duration_seconds",
        "frame_rate",
        "preview_frame_count",
        "final_frame_count",
        "longest_static_seconds",
        "repair_count",
        "diagnostic_codes",
        "repeated_signature",
        "analysis_elapsed_ms",
        "provenance_version",
    }
    if not required <= set(case):
        raise AcceptanceFailure("invalid_golden_case")
    identifier = case["id"]
    if not isinstance(identifier, str) or not re.fullmatch(r"[FG][0-9]{2}", identifier):
        raise AcceptanceFailure("invalid_golden_case")
    if identifier in identifiers or case["category"] not in VALID_CATEGORIES:
        raise AcceptanceFailure("invalid_golden_case")
    identifiers.add(identifier)
    if case["terminal_status"] not in TERMINAL_STATUSES:
        raise AcceptanceFailure("invalid_golden_case")
    if not isinstance(case["coverage"], list) or not case["coverage"]:
        raise AcceptanceFailure("invalid_golden_case")
    numeric_fields = required - {
        "id",
        "category",
        "coverage",
        "terminal_status",
        "diagnostic_codes",
        "repeated_signature",
        "provenance_version",
    }
    measured_fields = (field for field in numeric_fields if field != "repair_count")
    if any(not _positive_number(case[field]) for field in measured_fields):
        raise AcceptanceFailure("invalid_golden_case")
    if not isinstance(case["repair_count"], int) or not 0 <= case["repair_count"] <= 2:
        raise AcceptanceFailure("invalid_golden_case")
    if not isinstance(case["diagnostic_codes"], list) or not all(
        isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{2,99}", code)
        for code in case["diagnostic_codes"]
    ):
        raise AcceptanceFailure("invalid_golden_case")
    if not isinstance(case["repeated_signature"], bool) or not isinstance(
        case["provenance_version"], str
    ):
        raise AcceptanceFailure("invalid_golden_case")


def _validate_terminal_record(record: Mapping[str, Any], expected_status: object) -> None:
    status = record.get("terminal_status")
    if status not in TERMINAL_STATUSES:
        if record.get("repeated_signature") is True:
            raise AcceptanceFailure("repeat_signature_loop")
        raise AcceptanceFailure("non_terminal_quality_state")
    if record.get("cross_owner_access") != "denied":
        raise AcceptanceFailure("owner_isolation_failed")
    if not isinstance(record.get("repair_count"), int) or record["repair_count"] > 2:
        raise AcceptanceFailure("repair_budget_exceeded")
    if record.get("repeated_signature") is True and status not in {"failed", "degraded"}:
        raise AcceptanceFailure("repeat_signature_loop")
    for field in (
        "target_duration_seconds",
        "estimated_duration_seconds",
        "actual_duration_seconds",
        "frame_rate",
        "frame_count",
        "analysis_elapsed_ms",
    ):
        if not _positive_number(record.get(field)):
            raise AcceptanceFailure("invalid_terminal_record")
    if record["analysis_elapsed_ms"] > 2_500:
        raise AcceptanceFailure("performance_budget_exceeded")
    codes = record.get("diagnostic_codes")
    required_codes = record.get("required_diagnostic_codes")
    if not isinstance(codes, list) or not isinstance(required_codes, list):
        raise AcceptanceFailure("invalid_terminal_record")
    actual = float(record["actual_duration_seconds"])
    target = float(record["target_duration_seconds"])
    if actual < target * 0.9 and "duration_too_short" not in codes:
        raise AcceptanceFailure("duration_diagnostic_missing")
    if actual > target * 1.1 and "duration_too_long" not in codes:
        raise AcceptanceFailure("duration_diagnostic_missing")
    static_limit = max(5.0, target * 0.2)
    if float(record.get("longest_static_seconds", 0.0)) > static_limit and not {
        "long_static_segment",
        "terminal_wait_padding",
    } & set(codes):
        raise AcceptanceFailure("static_padding_undetected")
    if not set(required_codes) <= set(codes):
        raise AcceptanceFailure("expected_diagnostic_missing")
    if status == "passed" and SEVERE_CODES & set(codes):
        raise AcceptanceFailure("severe_diagnostic_passed")
    if status != expected_status:
        raise AcceptanceFailure("unexpected_terminal_status")
    if record.get("diagnostic_signature") != record.get("replay_signature"):
        raise AcceptanceFailure("determinism_mismatch")
    if record.get("provenance_version") != "phase9-v1":
        raise AcceptanceFailure("version_regression_detected")


def _validate_pair(preview: Mapping[str, Any], final: Mapping[str, Any]) -> None:
    preview_timing = _frame_timing(preview)
    final_timing = _frame_timing(final)
    allowed = _allowed_frame_delta(preview, final)
    if abs(preview_timing - final_timing) > allowed + 1e-9:
        raise AcceptanceFailure("preview_final_frame_mismatch")
    actual_delta = abs(
        float(preview["actual_duration_seconds"]) - float(final["actual_duration_seconds"])
    )
    if actual_delta > allowed:
        raise AcceptanceFailure("preview_final_timeline_mismatch")


def _metrics(
    records: Sequence[Mapping[str, Any]],
    records_by_case: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> dict[str, int | float]:
    frame_agreement = sum(
        abs(_frame_timing(pair["preview"]) - _frame_timing(pair["final"]))
        <= _allowed_frame_delta(pair["preview"], pair["final"]) + 1e-9
        for pair in records_by_case.values()
    )
    return {
        "golden_cases": len(records_by_case),
        "terminal_records": len(records),
        "terminal_completeness_percent": 100.0,
        "quality_pass_rate_percent": 100.0,
        "deterministic_pairs": sum(
            pair["preview"]["diagnostic_signature"] == pair["preview"]["replay_signature"]
            and pair["final"]["diagnostic_signature"] == pair["final"]["replay_signature"]
            for pair in records_by_case.values()
        ),
        "owner_isolation_denied_records": sum(
            record["cross_owner_access"] == "denied" for record in records
        ),
        "preview_final_one_frame_agreement_pairs": frame_agreement,
        "max_repair_count": max(int(record["repair_count"]) for record in records),
        "performance_records_within_budget": sum(
            float(record["analysis_elapsed_ms"]) <= 2_500 for record in records
        ),
    }


def _assert_metric_baseline(
    metrics: Mapping[str, int | float], baseline: Mapping[str, Any]
) -> None:
    minimums = baseline.get("minimum_metrics")
    if not isinstance(minimums, Mapping):
        raise AcceptanceFailure("invalid_metrics_baseline")
    for key, minimum in minimums.items():
        value = metrics.get(key)
        if not isinstance(minimum, int | float) or not isinstance(value, int | float):
            raise AcceptanceFailure("invalid_metrics_baseline")
        if key == "max_repair_count":
            if value > minimum:
                raise AcceptanceFailure("metric_regression")
        elif value < minimum:
            raise AcceptanceFailure("metric_regression")


def _reject_sensitive_values(value: object) -> None:
    for text in _string_values(value):
        if SECRET_OR_ABSOLUTE_VALUE.search(text):
            raise AcceptanceFailure("unsafe_corpus_content")


def _string_values(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for nested in value.values():
            yield from _string_values(nested)
    elif isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        for nested in value:
            yield from _string_values(nested)


def _signature(case_id: object, profile: object, codes: object) -> str:
    payload = json.dumps([case_id, profile, codes], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _positive_number(value: object) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _frame_timing(record: Mapping[str, Any]) -> float:
    return float(record["frame_count"]) / float(record["frame_rate"])


def _allowed_frame_delta(preview: Mapping[str, Any], final: Mapping[str, Any]) -> float:
    return 1.0 / max(float(preview["frame_rate"]), float(final["frame_rate"]))
