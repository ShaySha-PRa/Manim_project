from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CATEGORIES = {"formula_derivation", "function_visualization"}
AUDIENCES = {"k12", "college", "general_creator"}
DIFFICULTIES = {"introductory", "intermediate", "advanced"}
REQUIRED_FIELDS = {
    "id",
    "category",
    "persona",
    "audience",
    "difficulty",
    "topic",
    "prompt",
    "teaching_goal",
    "must_include",
    "must_avoid",
    "expected_scene_structure",
    "duration_seconds",
    "correctness_checks",
    "ambiguities",
    "source",
    "review",
}


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidationReport:
    total: int
    by_category: dict[str, int]


def _require_non_empty_string(entry: dict[str, Any], field: str, location: str) -> None:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{location}: {field} must be a non-empty string")


def _require_string_list(
    entry: dict[str, Any], field: str, location: str, *, allow_empty: bool = False
) -> None:
    value = entry.get(field)
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValidationError(f"{location}: {field} must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError(f"{location}: {field} must contain non-empty strings")


def _validate_duration(entry: dict[str, Any], location: str) -> None:
    duration = entry.get("duration_seconds")
    if not isinstance(duration, dict) or set(duration) != {"min", "target", "max"}:
        raise ValidationError(f"{location}: duration must contain min, target, and max")
    values = [duration["min"], duration["target"], duration["max"]]
    if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
        raise ValidationError(f"{location}: duration values must be integers")
    if not 30 <= values[0] <= values[1] <= values[2] <= 180:
        raise ValidationError(
            f"{location}: duration must satisfy 30 <= min <= target <= max <= 180"
        )


def _validate_source_and_review(entry: dict[str, Any], location: str) -> None:
    source = entry.get("source")
    if not isinstance(source, dict):
        raise ValidationError(f"{location}: source must be an object")
    if set(source) != {"type", "agent", "interview_id"}:
        raise ValidationError(
            f"{location}: source fields must be type, agent, and interview_id"
        )
    if source.get("type") not in {"synthetic_interview", "real_interview"}:
        raise ValidationError(f"{location}: source.type is unsupported")
    for field in ("agent", "interview_id"):
        if not isinstance(source.get(field), str) or not source[field].strip():
            raise ValidationError(f"{location}: source.{field} must be non-empty")

    review = entry.get("review")
    if not isinstance(review, dict):
        raise ValidationError(f"{location}: review must be an object")
    if set(review) != {"status", "notes"}:
        raise ValidationError(f"{location}: review fields must be status and notes")
    if review.get("status") != "parent_validated":
        raise ValidationError(f"{location}: review.status must be parent_validated")
    if not isinstance(review.get("notes"), str) or not review["notes"].strip():
        raise ValidationError(f"{location}: review.notes must be non-empty")


def _validate_entry(entry: Any, line_number: int) -> dict[str, Any]:
    location = f"line {line_number}"
    if not isinstance(entry, dict):
        raise ValidationError(f"{location}: entry must be an object")
    missing = REQUIRED_FIELDS - set(entry)
    extra = set(entry) - REQUIRED_FIELDS
    if missing:
        raise ValidationError(f"{location}: missing fields: {sorted(missing)}")
    if extra:
        raise ValidationError(f"{location}: unsupported fields: {sorted(extra)}")

    for field in ("id", "persona", "topic", "prompt", "teaching_goal"):
        _require_non_empty_string(entry, field, location)
    for field in (
        "must_include",
        "must_avoid",
        "expected_scene_structure",
        "correctness_checks",
    ):
        _require_string_list(entry, field, location)
    _require_string_list(entry, "ambiguities", location, allow_empty=True)

    if entry["category"] not in CATEGORIES:
        raise ValidationError(f"{location}: unsupported category {entry['category']!r}")
    if entry["audience"] not in AUDIENCES:
        raise ValidationError(f"{location}: unsupported audience {entry['audience']!r}")
    if entry["difficulty"] not in DIFFICULTIES:
        raise ValidationError(f"{location}: unsupported difficulty {entry['difficulty']!r}")

    expected_prefix = "formula" if entry["category"] == "formula_derivation" else "function"
    expected_pattern = rf"{expected_prefix}_[0-9]{{3}}"
    if re.fullmatch(expected_pattern, entry["id"]) is None:
        raise ValidationError(f"{location}: id must match {expected_pattern!r}")

    _validate_duration(entry, location)
    _validate_source_and_review(entry, location)
    return entry


def validate_dataset(
    path: Path, *, enforce_phase1_counts: bool = True
) -> ValidationReport:
    if not path.is_file():
        raise ValidationError(f"dataset not found: {path}")

    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            raise ValidationError(f"line {line_number}: blank lines are not allowed")
        try:
            raw_entry = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise ValidationError(f"line {line_number}: invalid JSON: {error.msg}") from error
        entry = _validate_entry(raw_entry, line_number)
        if entry["id"] in seen_ids:
            raise ValidationError(f"line {line_number}: duplicate id {entry['id']!r}")
        seen_ids.add(entry["id"])
        entries.append(entry)

    counts = Counter(entry["category"] for entry in entries)
    if enforce_phase1_counts:
        expected = {"formula_derivation": 15, "function_visualization": 15}
        if len(entries) != 30 or dict(counts) != expected:
            raise ValidationError(
                f"Phase 1 requires exactly 30 entries with category counts {expected}; "
                f"got total={len(entries)}, counts={dict(counts)}"
            )
    return ValidationReport(total=len(entries), by_category=dict(counts))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Phase 1 golden prompt set")
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("eval/gold_prompts.jsonl"),
    )
    args = parser.parse_args()
    try:
        report = validate_dataset(args.path)
    except ValidationError as error:
        print(f"INVALID: {error}")
        return 1
    print(f"VALID: total={report.total} categories={report.by_category}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
