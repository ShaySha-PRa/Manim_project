"""Fail-closed static safety gate for untrusted generated Manim source."""

from .validator import (
    SecurityFinding,
    SourceSecurityReport,
    complete_allowlisted_manim_imports,
    validate_source_security,
)

__all__ = [
    "SecurityFinding",
    "SourceSecurityReport",
    "complete_allowlisted_manim_imports",
    "validate_source_security",
]
