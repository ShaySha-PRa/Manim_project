from __future__ import annotations

from manim_workbench_contracts import CodeGenerationErrorCode


class CodeGenerationError(RuntimeError):
    """A stable, public-safe Phase 7 failure."""

    def __init__(
        self,
        code: CodeGenerationErrorCode,
        message: str,
        *,
        diagnostic_codes: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostic_codes = diagnostic_codes
