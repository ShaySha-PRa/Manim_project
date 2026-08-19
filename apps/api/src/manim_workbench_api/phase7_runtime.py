from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from manim_workbench_contracts import (
    CodeGenerationErrorCode,
    RenderJobFailureCode,
    RenderProfile,
)
from manim_workbench_runner.sandbox import SandboxExecutor, SandboxInvocation, SandboxLimits
from manim_workbench_runner.sandbox.executor import (
    SandboxExecutionCancelled,
    SandboxExecutionFailure,
    SandboxExecutionSuccess,
)
from manim_workbench_runner.sandbox.policy import memory_tier_for_source

from manim_workbench_api.code_generation.models import CandidateRenderResult
from manim_workbench_api.code_generation.validation import sanitize_diagnostic


class SandboxLike(Protocol):
    def execute(
        self, invocation: SandboxInvocation
    ) -> SandboxExecutionSuccess | SandboxExecutionFailure | SandboxExecutionCancelled: ...


_RESOURCE_FAILURES = {
    RenderJobFailureCode.SANDBOX_OOM,
    RenderJobFailureCode.SANDBOX_PID_LIMIT,
    RenderJobFailureCode.SANDBOX_OUTPUT_LIMIT,
}


class Phase7SandboxRenderer:
    """Render one validated candidate through the existing Phase 5 sandbox policy."""

    def __init__(self, *, runtime_root: Path, executor: SandboxLike | None = None) -> None:
        runtime_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._runtime_root = runtime_root.resolve(strict=True)
        self._source_root = self._runtime_root / "sources"
        self._output_root = self._runtime_root / "outputs"
        self._source_root.mkdir(exist_ok=True, mode=0o700)
        self._output_root.mkdir(exist_ok=True, mode=0o700)
        self._executor = executor or SandboxExecutor(
            limits=SandboxLimits(
                allowed_source_root=self._source_root,
                allowed_output_root=self._output_root,
            )
        )

    def render(self, source_code: str, scene_class: str) -> CandidateRenderResult:
        attempt_id = uuid4()
        source_directory = self._source_root / str(attempt_id)
        output_directory = self._output_root / str(attempt_id)
        source_directory.mkdir(mode=0o700)
        output_directory.mkdir(mode=0o700)
        source_path = source_directory / "scene.py"
        source_path.write_text(source_code, encoding="utf-8")
        source_path.chmod(0o600)
        invocation = SandboxInvocation(
            job_id=attempt_id,
            source_path=source_path,
            output_path=output_directory,
            scene_class=scene_class,
            profile=RenderProfile.PREVIEW,
            memory_tier=memory_tier_for_source(source_code),
        )
        try:
            result = self._executor.execute(invocation)
            return self._result(result)
        finally:
            shutil.rmtree(source_directory, ignore_errors=True)
            shutil.rmtree(output_directory, ignore_errors=True)

    @staticmethod
    def _result(
        result: SandboxExecutionSuccess | SandboxExecutionFailure | SandboxExecutionCancelled,
    ) -> CandidateRenderResult:
        if isinstance(result, SandboxExecutionSuccess):
            return CandidateRenderResult(succeeded=True)
        if isinstance(result, SandboxExecutionCancelled):
            return CandidateRenderResult(
                succeeded=False,
                error_code="internal_error",
                diagnostic="Candidate render was cancelled.",
            )
        if result.code is RenderJobFailureCode.SANDBOX_SECURITY_VIOLATION:
            error_code = "security_policy_violation"
        elif result.code is RenderJobFailureCode.SANDBOX_TIMEOUT:
            error_code = "sandbox_timeout"
        elif result.code in _RESOURCE_FAILURES:
            error_code = "sandbox_resource_limit"
        else:
            error_code = "render_failed"
        safe_diagnostic = sanitize_diagnostic(
            result.diagnostic or result.message,
            error_code=CodeGenerationErrorCode(error_code),
            stage="render",
            error_type="SandboxRenderError",
        )
        return CandidateRenderResult(
            succeeded=False,
            error_code=error_code,
            diagnostic=safe_diagnostic.message,
        )
