"""Compile-only and Scene-structure preflight for untrusted generated source."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from manim_workbench_contracts import CodeGenerationErrorCode

_REPAIRABLE_CODES = frozenset(
    {
        CodeGenerationErrorCode.INVALID_MODEL_RESPONSE,
        CodeGenerationErrorCode.RESPONSE_TOO_LARGE,
        CodeGenerationErrorCode.AST_PARSE_FAILED,
        CodeGenerationErrorCode.COMPILE_FAILED,
        CodeGenerationErrorCode.SCENE_STRUCTURE_INVALID,
        CodeGenerationErrorCode.RENDER_FAILED,
    }
)
_URL = re.compile(r"(?i)\b(?:https?|ftp)://[^\s'\"]+")
_BEARER = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_ENV_SECRET = re.compile(
    r"\b([A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|AUTHORIZATION|CREDENTIAL)[A-Z0-9_]*)"
    r"\s*([=:])\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_NAMED_SECRET = re.compile(
    r"(?i)\b(api[-_]?key|access[-_]?token|token|secret|password|authorization|credential)"
    r"\s*([=:])\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_PREFIXED_KEY = re.compile(r"(?<![A-Za-z0-9_])(?:sk|rk|pk)-[A-Za-z0-9_-]{8,}\b")
_HIGH_ENTROPY_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9])")
_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:(?:\\+[^\\\s:]+)+")
_UNIX_PATH = re.compile(r"(?<![A-Za-z0-9_])/(?:[^\s/:]+/)*[^\s/:]+")


@dataclass(frozen=True)
class Diagnostic:
    """A bounded, safe-to-persist summary of a validation failure."""

    stage: str
    error_code: CodeGenerationErrorCode
    error_type: str
    message: str
    line_number: int | None = None
    repairable: bool = False


@dataclass(frozen=True)
class PreflightReport:
    """The deterministic result of compile-only and Scene-shape validation."""

    ok: bool
    diagnostic: Diagnostic | None = None


def preflight_source(source: str) -> PreflightReport:
    """Compile and inspect source without importing or executing it.

    This function runs only after the separate AST security gate has accepted
    the candidate.  It intentionally does not enforce imports or permitted
    Manim APIs; its job is limited to compilation and the exact Scene shape.
    """
    try:
        compile(source, "<generated-source>", "exec", dont_inherit=True)
    except (SyntaxError, TypeError, ValueError, OverflowError) as error:
        return _failure(
            stage="compile",
            error_code=CodeGenerationErrorCode.COMPILE_FAILED,
            error_type=type(error).__name__,
            message=str(error),
            line_number=getattr(error, "lineno", None),
        )

    try:
        tree = ast.parse(source, filename="<generated-source>", mode="exec")
    except SyntaxError as error:  # Defensive: compile() above normally catches this first.
        return _failure(
            stage="compile",
            error_code=CodeGenerationErrorCode.COMPILE_FAILED,
            error_type=type(error).__name__,
            message=str(error),
            line_number=error.lineno,
        )

    structure_error = _scene_structure_error(tree)
    if structure_error is not None:
        return _failure(
            stage="scene_structure",
            error_code=CodeGenerationErrorCode.SCENE_STRUCTURE_INVALID,
            error_type="SceneStructureError",
            message=structure_error,
        )
    return PreflightReport(ok=True)


def sanitize_diagnostic(
    diagnostic: Diagnostic | str,
    *,
    error_code: CodeGenerationErrorCode | None = None,
    stage: str | None = None,
    error_type: str | None = None,
    line_number: int | None = None,
) -> Diagnostic:
    """Return a bounded diagnostic with secrets and host details removed.

    Supplied error codes determine repair eligibility.  This prevents callers
    from accidentally marking provider, security, or infrastructure failures
    as repairable merely by setting a boolean on a diagnostic object.
    """
    if isinstance(diagnostic, Diagnostic):
        message = diagnostic.message
        resolved_code = diagnostic.error_code
        resolved_stage = diagnostic.stage
        resolved_type = diagnostic.error_type
        resolved_line = diagnostic.line_number
    else:
        if error_code is None or stage is None:
            raise ValueError("error_code and stage are required for diagnostic text")
        message = diagnostic
        resolved_code = error_code
        resolved_stage = stage
        resolved_type = error_type or "Diagnostic"
        resolved_line = line_number

    return Diagnostic(
        stage=resolved_stage,
        error_code=resolved_code,
        error_type=resolved_type,
        message=_sanitize_text(message),
        line_number=resolved_line,
        repairable=resolved_code in _REPAIRABLE_CODES,
    )


def _failure(
    *,
    stage: str,
    error_code: CodeGenerationErrorCode,
    error_type: str,
    message: str,
    line_number: int | None = None,
) -> PreflightReport:
    return PreflightReport(
        ok=False,
        diagnostic=sanitize_diagnostic(
            message,
            error_code=error_code,
            stage=stage,
            error_type=error_type,
            line_number=line_number,
        ),
    )


def _scene_structure_error(tree: ast.Module) -> str | None:
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    if len(classes) != 1:
        return "source must define exactly one class"

    scene = classes[0]
    if scene not in tree.body or scene.name != "GeneratedScene":
        return "the only top-level class must be GeneratedScene"
    if scene.decorator_list:
        return "GeneratedScene must not use decorators"
    if len(scene.bases) != 1 or not isinstance(scene.bases[0], ast.Name):
        return "GeneratedScene must directly inherit Scene"
    if scene.bases[0].id != "Scene":
        return "GeneratedScene must directly inherit Scene"
    if scene.keywords:
        return "GeneratedScene may not use class keywords"
    return None


def _sanitize_text(message: str) -> str:
    cleaned = _URL.sub("[REDACTED_URL]", message)
    cleaned = _BEARER.sub("Bearer [REDACTED]", cleaned)
    cleaned = _ENV_SECRET.sub(r"\1\2[REDACTED]", cleaned)
    cleaned = _NAMED_SECRET.sub(r"\1\2[REDACTED]", cleaned)
    cleaned = _PREFIXED_KEY.sub("[REDACTED_SECRET]", cleaned)
    cleaned = _HIGH_ENTROPY_TOKEN.sub("[REDACTED_SECRET]", cleaned)
    cleaned = _WINDOWS_PATH.sub("[REDACTED_PATH]", cleaned)
    cleaned = _UNIX_PATH.sub("[REDACTED_PATH]", cleaned)
    lines = cleaned.splitlines()
    if len(lines) > 20:
        lines = [*lines[:8], "[TRUNCATED]", *lines[-11:]]
    lines = [line[:180] for line in lines]
    return "\n".join(lines)[:4000]


__all__ = ["Diagnostic", "PreflightReport", "preflight_source", "sanitize_diagnostic"]
