"""Strict untrusted-output boundary for workflow Director planning."""

from __future__ import annotations

import json
import re
from typing import Any

from manim_workbench_contracts import DirectorDraft
from pydantic import ValidationError

_MAX_CANDIDATE_BYTES = 64 * 1024
_FORBIDDEN_KEYS = {
    "animation_ir",
    "edges",
    "nodes",
    "source",
    "source_code",
    "tool",
    "tool_call",
    "tool_calls",
    "tools",
}
_EXECUTABLE_TEXT = re.compile(
    r"```|\bfrom\s+manim\s+import\b|\bclass\s+GeneratedScene\b|\blambda\b|"
    r"\b(?:eval|exec|compile|open)\s*\(",
    re.IGNORECASE,
)


class DirectorCandidateError(ValueError):
    """A stable, non-sensitive rejection of one untrusted Director candidate."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DirectorCandidateError("director_duplicate_json_key", "duplicate JSON key")
        result[key] = value
    return result


def _validate_safe_tree(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in _FORBIDDEN_KEYS:
                raise DirectorCandidateError(
                    "director_security_violation", "candidate contains a forbidden field"
                )
            _validate_safe_tree(item)
        return
    if isinstance(value, list):
        for item in value:
            _validate_safe_tree(item)
        return
    if isinstance(value, str) and _EXECUTABLE_TEXT.search(value):
        raise DirectorCandidateError(
            "director_security_violation", "candidate contains executable content"
        )


def parse_director_candidate(candidate: str) -> DirectorDraft:
    """Parse exactly one bounded JSON object into the strict Director draft contract."""

    if len(candidate.encode("utf-8")) > _MAX_CANDIDATE_BYTES:
        raise DirectorCandidateError("director_candidate_too_large", "candidate is too large")
    if not candidate.strip():
        raise DirectorCandidateError("director_invalid_json", "candidate is empty")
    try:
        payload = json.loads(candidate, object_pairs_hook=_reject_duplicate_keys)
    except DirectorCandidateError:
        raise
    except (json.JSONDecodeError, UnicodeError) as error:
        raise DirectorCandidateError(
            "director_invalid_json", "candidate must be one JSON object"
        ) from error
    if not isinstance(payload, dict):
        raise DirectorCandidateError("director_invalid_schema", "candidate must be an object")
    _validate_safe_tree(payload)
    try:
        return DirectorDraft.model_validate(payload)
    except ValidationError as error:
        raise DirectorCandidateError(
            "director_invalid_schema", "candidate does not match the Director schema"
        ) from error


__all__ = ["DirectorCandidateError", "parse_director_candidate"]
