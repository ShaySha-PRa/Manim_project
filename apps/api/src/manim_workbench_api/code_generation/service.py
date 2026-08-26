from __future__ import annotations

import hashlib
from dataclasses import replace

from manim_workbench_contracts import (
    CodeGenerationCategory,
    CodeGenerationErrorCode,
    CodeGenerationMode,
    CodeGenerationOutcome,
    CodeGenerationRequest,
    CodeGenerationResponse,
    CodeModelResponse,
    QualitySeverity,
)

from manim_workbench_api.compiler.base import CompiledProgram
from manim_workbench_api.content_plans.errors import ContentPlanError, ContentPlanErrorCode
from manim_workbench_api.content_plans.models import ProviderMessage, ProviderResult
from manim_workbench_api.quality.orchestration import diagnose_content_plan_timeline

from .errors import CodeGenerationError
from .ir_compiler import (
    IrCompileError,
    compile_storyboard,
    compiled_segment_as_response,
    synthesize_storyboard,
)
from .models import CandidateRenderer, CodeGenerationProvider
from .prompts import (
    PROMPT_TEMPLATE_VERSION,
    build_code_generation_messages,
    parse_code_model_response,
)
from .repair import RepairAction, RepairOrchestrator, build_repair_messages
from .repository import CodeGenerationRepository
from .security import complete_allowlisted_manim_imports, validate_source_security
from .template_compiler import degrade_mathtex_to_text
from .validation import Diagnostic, preflight_source, sanitize_diagnostic

_PROVIDER_ERROR_MAP = {
    ContentPlanErrorCode.CONFIGURATION_ERROR: CodeGenerationErrorCode.PROVIDER_CONFIGURATION,
    ContentPlanErrorCode.PROVIDER_AUTH_ERROR: CodeGenerationErrorCode.PROVIDER_AUTHENTICATION,
    ContentPlanErrorCode.PROVIDER_RATE_LIMITED: CodeGenerationErrorCode.PROVIDER_UNAVAILABLE,
    ContentPlanErrorCode.PROVIDER_UNAVAILABLE: CodeGenerationErrorCode.PROVIDER_UNAVAILABLE,
    ContentPlanErrorCode.PROVIDER_EMPTY_RESPONSE: CodeGenerationErrorCode.INVALID_MODEL_RESPONSE,
    ContentPlanErrorCode.PROVIDER_TRUNCATED_RESPONSE: (
        CodeGenerationErrorCode.INVALID_MODEL_RESPONSE
    ),
    ContentPlanErrorCode.PROVIDER_INVALID_JSON: CodeGenerationErrorCode.INVALID_MODEL_RESPONSE,
    ContentPlanErrorCode.PROVIDER_SCHEMA_ERROR: CodeGenerationErrorCode.INVALID_MODEL_RESPONSE,
}
_TRANSIENT_PROVIDER_ERRORS = {
    ContentPlanErrorCode.PROVIDER_RATE_LIMITED,
    ContentPlanErrorCode.PROVIDER_UNAVAILABLE,
}

_IR_CATEGORIES = {
    CodeGenerationCategory.PLANE_GEOMETRY,
    CodeGenerationCategory.GEOMETRY_PROOF,
    CodeGenerationCategory.THREE_D,
    CodeGenerationCategory.MIXED,
}
_DETERMINISTIC_TEACHING_CATEGORIES = {
    CodeGenerationCategory.FORMULA_DERIVATION,
    CodeGenerationCategory.FUNCTION_VISUALIZATION,
}
_COMPILED_TEACHING_CATEGORIES = _DETERMINISTIC_TEACHING_CATEGORIES | _IR_CATEGORIES
_REPAIRABLE_STATIC_FINDINGS = {
    "forbidden_lambda",
    "invalid_assignment",
    "invalid_scene_class",
    "invalid_scene_structure",
    "invalid_function_signature",
    "unknown_manim_symbol",
    "unknown_attribute",
    "unknown_call",
    "unknown_name",
    "unsupported_syntax",
}


class CodeGenerationService:
    def __init__(
        self,
        repository: CodeGenerationRepository,
        provider: CodeGenerationProvider,
        renderer: CandidateRenderer,
        *,
        allow_legacy_free_python: bool = False,
    ) -> None:
        self._repository = repository
        self._provider = provider
        self._renderer = renderer
        self._allow_legacy_free_python = allow_legacy_free_python

    def compile_program(self, request: CodeGenerationRequest) -> CompiledProgram:
        """Compile and validate every teaching segment without selecting a canonical one."""
        loaded = self._repository.load_input(request)
        return self._compile_content_plan_program(request, loaded.content_plan)

    def generate(self, request: CodeGenerationRequest) -> CodeGenerationResponse:
        loaded = self._repository.load_input(request)
        plan = loaded.content_plan
        if not self._allow_legacy_free_python and request.category in _COMPILED_TEACHING_CATEGORIES:
            return self._generate_compiled_ir(request, plan)
        orchestrator = RepairOrchestrator(self._repository.load_category_policies())
        initial = orchestrator.initial_decision(request.category)
        if initial.action is RepairAction.PAUSE:
            return CodeGenerationResponse(
                outcome=CodeGenerationOutcome.PAUSED,
                attempts_used=0,
                mode=CodeGenerationMode.FULL,
                error_code=CodeGenerationErrorCode.GENERATION_PAUSED,
            )
        if initial.action is RepairAction.DETERMINISTIC_TEMPLATE:
            return self._generate_degraded(request, plan)
        if plan.storyboard is not None or request.category in _IR_CATEGORIES:
            return self._generate_compiled_ir(request, plan)

        messages = build_code_generation_messages(plan, request.category)
        attempt_number = 1
        while attempt_number <= 3:
            provider_result: ProviderResult | None = None
            candidate: CodeModelResponse | None = None
            try:
                provider_result = self._generate_with_transport_retry(messages)
                candidate = parse_code_model_response(provider_result.content)
            except ContentPlanError as error:
                code = _PROVIDER_ERROR_MAP.get(error.code, CodeGenerationErrorCode.INTERNAL_ERROR)
                decision = self._record_and_decide(
                    request=request,
                    orchestrator=orchestrator,
                    attempt_number=attempt_number,
                    code=code,
                    diagnostic=str(error),
                    provider_result=provider_result,
                    candidate=None,
                )
                if decision.action is RepairAction.REPAIR:
                    messages = _provider_messages(
                        build_repair_messages(
                            content_plan=plan.model_dump(mode="json"),
                            decision=decision,
                            diagnostic="Provider response did not satisfy the code contract.",
                        )
                    )
                    attempt_number = decision.attempt_number
                    continue
                return self._degrade_or_raise(request, plan, decision, code)
            except ValueError:
                code = CodeGenerationErrorCode.INVALID_MODEL_RESPONSE
                decision = self._record_and_decide(
                    request=request,
                    orchestrator=orchestrator,
                    attempt_number=attempt_number,
                    code=code,
                    diagnostic="Model response did not satisfy the code response contract.",
                    provider_result=provider_result,
                    candidate=None,
                )
                if decision.action is not RepairAction.REPAIR:
                    return self._degrade_or_raise(request, plan, decision, code)
                messages = _provider_messages(
                    build_repair_messages(
                        content_plan=plan.model_dump(mode="json"),
                        decision=decision,
                        diagnostic="Model response did not satisfy the code response contract.",
                    )
                )
                attempt_number = decision.attempt_number
                continue

            security = validate_source_security(candidate.code)
            normalized_source = complete_allowlisted_manim_imports(candidate.code, security)
            if normalized_source != candidate.code:
                candidate = candidate.model_copy(update={"code": normalized_source})
                security = validate_source_security(candidate.code)
            if not security.allowed:
                finding_codes = {finding.code for finding in security.findings}
                if finding_codes == {"parse_error"}:
                    code = CodeGenerationErrorCode.AST_PARSE_FAILED
                    line = security.findings[0].line
                    diagnostic = (
                        f"Candidate source has invalid Python syntax near line {line}."
                        if line is not None
                        else "Candidate source has invalid Python syntax."
                    )
                    decision = self._record_and_decide(
                        request=request,
                        orchestrator=orchestrator,
                        attempt_number=attempt_number,
                        code=code,
                        diagnostic=diagnostic,
                        provider_result=provider_result,
                        candidate=candidate,
                        candidate_sha256=security.source_sha256,
                    )
                    if decision.action is RepairAction.REPAIR:
                        messages = _provider_messages(
                            build_repair_messages(
                                content_plan=plan.model_dump(mode="json"),
                                decision=decision,
                                diagnostic=diagnostic,
                            )
                        )
                        attempt_number = decision.attempt_number
                        continue
                    return self._degrade_or_raise(request, plan, decision, code)
                if finding_codes and finding_codes <= _REPAIRABLE_STATIC_FINDINGS:
                    code = CodeGenerationErrorCode.STATIC_POLICY_REPAIRABLE
                    finding_diagnostics = tuple(
                        sorted(
                            f"{finding.code}:{finding.symbol}" if finding.symbol else finding.code
                            for finding in security.findings
                        )
                    )
                    diagnostic = "Static policy fixes required: " + ", ".join(finding_diagnostics)
                    decision = self._record_and_decide(
                        request=request,
                        orchestrator=orchestrator,
                        attempt_number=attempt_number,
                        code=code,
                        diagnostic=diagnostic,
                        provider_result=provider_result,
                        candidate=candidate,
                        candidate_sha256=security.source_sha256,
                    )
                    if decision.action is RepairAction.REPAIR:
                        messages = _provider_messages(
                            build_repair_messages(
                                content_plan=plan.model_dump(mode="json"),
                                decision=decision,
                                diagnostic=diagnostic,
                            )
                        )
                        attempt_number = decision.attempt_number
                        continue
                    if decision.error_code is CodeGenerationErrorCode.ATTEMPT_BUDGET_EXHAUSTED:
                        return self._generate_degraded(
                            request, plan, attempts_used=decision.attempt_number
                        )
                    resolved = decision.error_code or code
                    resolved = (
                        resolved
                        if isinstance(resolved, CodeGenerationErrorCode)
                        else CodeGenerationErrorCode(resolved)
                    )
                    raise CodeGenerationError(
                        resolved,
                        "Code generation failed.",
                        diagnostic_codes=finding_diagnostics,
                    )
                self._record_failure(
                    request=request,
                    attempt_number=attempt_number,
                    code=CodeGenerationErrorCode.SECURITY_POLICY_VIOLATION,
                    diagnostic="Static source security policy rejected the candidate.",
                    provider_result=provider_result,
                    candidate_sha256=security.source_sha256,
                )
                raise CodeGenerationError(
                    CodeGenerationErrorCode.SECURITY_POLICY_VIOLATION,
                    "Generated source did not satisfy the security policy.",
                    diagnostic_codes=tuple(
                        sorted(
                            f"{finding.code}:{finding.symbol}" if finding.symbol else finding.code
                            for finding in security.findings
                        )
                    ),
                )

            preflight = preflight_source(candidate.code)
            if not preflight.ok:
                assert preflight.diagnostic is not None
                decision = self._record_and_decide(
                    request=request,
                    orchestrator=orchestrator,
                    attempt_number=attempt_number,
                    code=preflight.diagnostic.error_code,
                    diagnostic=preflight.diagnostic.message,
                    provider_result=provider_result,
                    candidate=candidate,
                    candidate_sha256=security.source_sha256,
                )
                if decision.action is RepairAction.REPAIR:
                    messages = self._repair_messages(
                        plan, decision, preflight.diagnostic, candidate
                    )
                    attempt_number = decision.attempt_number
                    continue
                return self._degrade_or_raise(
                    request, plan, decision, preflight.diagnostic.error_code
                )

            _temporal, quality_diagnostics = diagnose_content_plan_timeline(
                source_code=candidate.code,
                content_plan=plan,
            )
            blocking_quality = tuple(
                item for item in quality_diagnostics if item.severity is QualitySeverity.ERROR
            )
            if blocking_quality:
                details = []
                for item in blocking_quality:
                    measurements = []
                    if item.measured_value is not None:
                        measurements.append(f"measured={item.measured_value}")
                    if item.threshold_value is not None:
                        measurements.append(f"threshold={item.threshold_value}")
                    suffix = f" ({', '.join(measurements)})" if measurements else ""
                    details.append(f"{item.code.value}: {item.message}{suffix}. {item.suggestion}")
                diagnostic = "Timeline quality fixes required: " + "; ".join(details)
                decision = self._record_and_decide(
                    request=request,
                    orchestrator=orchestrator,
                    attempt_number=attempt_number,
                    code=CodeGenerationErrorCode.SCENE_STRUCTURE_INVALID,
                    diagnostic=diagnostic,
                    provider_result=provider_result,
                    candidate=candidate,
                    candidate_sha256=security.source_sha256,
                )
                if decision.action is RepairAction.REPAIR:
                    messages = _provider_messages(
                        build_repair_messages(
                            content_plan=plan.model_dump(mode="json"),
                            decision=decision,
                            diagnostic=diagnostic,
                            candidate_source=candidate.code,
                        )
                    )
                    attempt_number = decision.attempt_number
                    continue
                return self._degrade_or_raise(
                    request,
                    plan,
                    decision,
                    CodeGenerationErrorCode.SCENE_STRUCTURE_INVALID,
                )

            render = self._renderer.render(candidate.code, candidate.scene_class)
            if not render.succeeded:
                code = _render_error_code(render.error_code)
                diagnostic = sanitize_diagnostic(
                    render.diagnostic or "Sandbox candidate render failed.",
                    error_code=code,
                    stage="render",
                    error_type="SandboxRenderError",
                )
                if attempt_number == 3 and "latex error converting to dvi" in (
                    diagnostic.message.lower()
                ):
                    degraded = self._try_latex_text_degraded(
                        request=request,
                        candidate=candidate,
                        attempt_number=attempt_number,
                        provider_result=provider_result,
                    )
                    if degraded is not None:
                        return degraded
                decision = self._record_and_decide(
                    request=request,
                    orchestrator=orchestrator,
                    attempt_number=attempt_number,
                    code=code,
                    diagnostic=diagnostic.message,
                    provider_result=provider_result,
                    candidate=candidate,
                    candidate_sha256=security.source_sha256,
                )
                if decision.action is RepairAction.REPAIR:
                    messages = self._repair_messages(plan, decision, diagnostic, candidate)
                    attempt_number = decision.attempt_number
                    continue
                return self._degrade_or_raise(request, plan, decision, code)

            version = self._repository.save_success(
                request,
                response=candidate,
                attempt_number=attempt_number,
                mode=CodeGenerationMode.FULL,
                prompt_template_version=PROMPT_TEMPLATE_VERSION,
                provider_model=provider_result.model,
            )
            return CodeGenerationResponse(
                outcome=CodeGenerationOutcome.READY,
                code_version=version,
                attempts_used=attempt_number,
                mode=CodeGenerationMode.FULL,
            )
        raise AssertionError("three-attempt loop must return or raise")

    def _generate_compiled_ir(self, request, plan):  # type: ignore[no-untyped-def]
        program = self._compile_content_plan_program(request, plan)
        if program.requires_concat:
            raise CodeGenerationError(
                CodeGenerationErrorCode.SCENE_STRUCTURE_INVALID,
                "Multi-segment teaching programs require ProgramRenderService.",
            )
        (segment,) = program.segments
        candidate = compiled_segment_as_response(segment)
        render = self._renderer.render(candidate.code, candidate.scene_class)
        if not render.succeeded:
            raise CodeGenerationError(
                _render_error_code(render.error_code),
                "Compiled IR render failed.",
            )
        version = self._repository.save_success(
            request,
            response=candidate,
            attempt_number=1,
            mode=CodeGenerationMode.COMPILED_IR,
            prompt_template_version="teaching-storyboard-v1",
            provider_model=None,
        )
        return CodeGenerationResponse(
            outcome=CodeGenerationOutcome.READY,
            code_version=version,
            attempts_used=1,
            mode=CodeGenerationMode.COMPILED_IR,
        )

    def _compile_content_plan_program(
        self,
        request: CodeGenerationRequest,
        plan,  # type: ignore[no-untyped-def]
    ) -> CompiledProgram:
        expressions = tuple(
            step.expression for scene in plan.scenes for step in scene.formula_steps
        )
        explanations = tuple(
            step.explanation for scene in plan.scenes for step in scene.formula_steps
        )
        try:
            storyboard = plan.storyboard
            if storyboard is None:
                if request.category not in _DETERMINISTIC_TEACHING_CATEGORIES:
                    raise IrCompileError(
                        f"{request.category.value} requires a validated SceneStoryboard"
                    )
                storyboard = synthesize_storyboard(
                    title=plan.title,
                    target_duration_seconds=plan.target_duration_seconds,
                    category=request.category.value,
                    expressions=expressions,
                    explanations=explanations,
                )
            program = compile_storyboard(storyboard)
        except (IrCompileError, ValueError) as error:
            raise CodeGenerationError(
                CodeGenerationErrorCode.INVALID_MODEL_RESPONSE,
                f"Scene IR could not be compiled: {error}",
            ) from error
        normalized_segments = []
        for segment in program.segments:
            candidate = compiled_segment_as_response(segment)
            security = validate_source_security(candidate.code)
            normalized = complete_allowlisted_manim_imports(candidate.code, security)
            if normalized != candidate.code:
                candidate = candidate.model_copy(update={"code": normalized})
                security = validate_source_security(candidate.code)
            if not security.allowed:
                raise CodeGenerationError(
                    CodeGenerationErrorCode.SECURITY_POLICY_VIOLATION,
                    "Compiled IR did not satisfy the security policy.",
                )
            if not preflight_source(candidate.code).ok:
                raise CodeGenerationError(
                    CodeGenerationErrorCode.SCENE_STRUCTURE_INVALID,
                    "Compiled IR failed scene preflight.",
                )
            normalized_segments.append(replace(segment, source=candidate.code))
        program = replace(program, segments=tuple(normalized_segments))
        if request.category in _DETERMINISTIC_TEACHING_CATEGORIES:
            for segment in program.segments:
                _temporal, diagnostics = diagnose_content_plan_timeline(
                    source_code=segment.source,
                    content_plan=plan,
                )
                blocking = tuple(
                    diagnostic
                    for diagnostic in diagnostics
                    if diagnostic.severity is QualitySeverity.ERROR
                )
                if blocking:
                    codes = ",".join(sorted({item.code.value for item in blocking}))
                    raise CodeGenerationError(
                        CodeGenerationErrorCode.SCENE_STRUCTURE_INVALID,
                        f"Compiled teaching scene failed quality validation: {codes}",
                    )
        return program

    def _try_latex_text_degraded(
        self,
        *,
        request: CodeGenerationRequest,
        candidate: CodeModelResponse,
        attempt_number: int,
        provider_result: ProviderResult,
    ) -> CodeGenerationResponse | None:
        degraded_source = degrade_mathtex_to_text(candidate.code)
        if degraded_source == candidate.code:
            return None
        degraded_candidate = candidate.model_copy(update={"code": degraded_source})
        security = validate_source_security(degraded_candidate.code)
        if not security.allowed or not preflight_source(degraded_candidate.code).ok:
            return None
        render = self._renderer.render(degraded_candidate.code, degraded_candidate.scene_class)
        if not render.succeeded:
            return None
        version = self._repository.save_success(
            request,
            response=degraded_candidate,
            attempt_number=attempt_number,
            mode=CodeGenerationMode.DETERMINISTIC_TEMPLATE,
            prompt_template_version="phase7-latex-text-degraded-v1",
            provider_model=provider_result.model,
        )
        return CodeGenerationResponse(
            outcome=CodeGenerationOutcome.DEGRADED,
            code_version=version,
            attempts_used=attempt_number,
            mode=CodeGenerationMode.DETERMINISTIC_TEMPLATE,
        )

    def _generate_degraded(self, request, plan, *, attempts_used: int = 0):  # type: ignore[no-untyped-def]
        from .template_compiler import compile_deterministic_template

        candidate = compile_deterministic_template(plan, request.category)
        security = validate_source_security(candidate.code)
        preflight = preflight_source(candidate.code) if security.allowed else None
        if not security.allowed or preflight is None or not preflight.ok:
            raise CodeGenerationError(
                CodeGenerationErrorCode.INTERNAL_ERROR,
                "Deterministic template did not satisfy validation.",
            )
        _temporal, quality_diagnostics = diagnose_content_plan_timeline(
            source_code=candidate.code,
            content_plan=plan,
        )
        if any(item.severity is QualitySeverity.ERROR for item in quality_diagnostics):
            raise CodeGenerationError(
                CodeGenerationErrorCode.INTERNAL_ERROR,
                "Deterministic template did not satisfy quality validation.",
            )
        render = self._renderer.render(candidate.code, candidate.scene_class)
        if not render.succeeded:
            raise CodeGenerationError(
                _render_error_code(render.error_code),
                "Deterministic template render failed.",
            )
        version = self._repository.save_success(
            request,
            response=candidate,
            attempt_number=max(1, attempts_used),
            mode=CodeGenerationMode.DETERMINISTIC_TEMPLATE,
            prompt_template_version="phase7-deterministic-v1",
            provider_model=None,
        )
        return CodeGenerationResponse(
            outcome=CodeGenerationOutcome.DEGRADED,
            code_version=version,
            attempts_used=attempts_used,
            mode=CodeGenerationMode.DETERMINISTIC_TEMPLATE,
        )

    def _degrade_or_raise(self, request, plan, decision, code):  # type: ignore[no-untyped-def]
        if decision.error_code is CodeGenerationErrorCode.ATTEMPT_BUDGET_EXHAUSTED:
            try:
                return self._generate_degraded(
                    request,
                    plan,
                    attempts_used=decision.attempt_number,
                )
            except CodeGenerationError as error:
                raise CodeGenerationError(
                    CodeGenerationErrorCode.ATTEMPT_BUDGET_EXHAUSTED,
                    "Code generation and deterministic fallback failed.",
                ) from error
        self._raise_decision(decision.error_code or code)

    def _record_and_decide(
        self,
        *,
        request,
        orchestrator,
        attempt_number,
        code,
        diagnostic,
        provider_result,
        candidate,
        candidate_sha256=None,
    ):  # type: ignore[no-untyped-def]
        self._record_failure(
            request=request,
            attempt_number=attempt_number,
            code=code,
            diagnostic=diagnostic,
            provider_result=provider_result,
            candidate_sha256=candidate_sha256 or _candidate_sha256(candidate),
        )
        return orchestrator.failure_decision(
            request.category,
            attempt_number=attempt_number,
            error_code=code,
        )

    def _record_failure(
        self,
        *,
        request,
        attempt_number,
        code,
        diagnostic,
        provider_result,
        candidate_sha256,
    ):  # type: ignore[no-untyped-def]
        safe = sanitize_diagnostic(
            diagnostic,
            error_code=code,
            stage="generation",
            error_type="CodeGenerationFailure",
        )
        self._repository.record_failed_attempt(
            request,
            attempt_number=attempt_number,
            error_code=code,
            provider_model=provider_result.model if provider_result else None,
            candidate_sha256=candidate_sha256,
            diagnostic_sha256=hashlib.sha256(safe.message.encode("utf-8")).hexdigest(),
        )

    @staticmethod
    def _repair_messages(plan, decision, diagnostic: Diagnostic, candidate):  # type: ignore[no-untyped-def]
        return _provider_messages(
            build_repair_messages(
                content_plan=plan.model_dump(mode="json"),
                decision=decision,
                diagnostic=diagnostic.message,
                candidate_source=(candidate.code if decision.include_candidate_source else None),
            )
        )

    def _generate_with_transport_retry(
        self, messages: tuple[ProviderMessage, ...]
    ) -> ProviderResult:
        for transport_attempt in (1, 2, 3):
            try:
                return self._provider.generate(messages)
            except ContentPlanError as error:
                if error.code in _TRANSIENT_PROVIDER_ERRORS and transport_attempt < 3:
                    continue
                raise
        raise AssertionError("bounded provider transport retry must return or raise")

    @staticmethod
    def _raise_decision(code) -> None:  # type: ignore[no-untyped-def]
        resolved = (
            code if isinstance(code, CodeGenerationErrorCode) else CodeGenerationErrorCode(code)
        )
        raise CodeGenerationError(resolved, "Code generation failed.")


def _provider_messages(messages: tuple[dict[str, str], ...]) -> tuple[ProviderMessage, ...]:
    return tuple(ProviderMessage.model_validate(message) for message in messages)


def _candidate_sha256(candidate: CodeModelResponse | None) -> str | None:
    if candidate is None:
        return None
    return hashlib.sha256(candidate.code.encode("utf-8")).hexdigest()


def _render_error_code(value: str | None) -> CodeGenerationErrorCode:
    try:
        return CodeGenerationErrorCode(value or "render_failed")
    except ValueError:
        return CodeGenerationErrorCode.INTERNAL_ERROR
