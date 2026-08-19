from __future__ import annotations

import argparse
import json
import re
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from manim_workbench_api.code_generation.errors import CodeGenerationError
from manim_workbench_api.code_generation.models import LoadedCodeGenerationInput
from manim_workbench_api.code_generation.repair import CategoryPolicy
from manim_workbench_api.code_generation.security import validate_source_security
from manim_workbench_api.code_generation.service import CodeGenerationService
from manim_workbench_api.content_plans.errors import ContentPlanError, ContentPlanSemanticError
from manim_workbench_api.content_plans.models import ProviderMessage
from manim_workbench_api.content_plans.prompts import build_content_plan_messages
from manim_workbench_api.content_plans.provider import DeepSeekProvider
from manim_workbench_api.content_plans.service import ContentPlanService
from manim_workbench_api.content_plans.validation import validate_content_plan_response
from manim_workbench_api.phase7_runtime import Phase7SandboxRenderer
from manim_workbench_contracts import (
    CodeGenerationCategory,
    CodeGenerationMode,
    CodeGenerationRequest,
    CodeModelResponse,
    CodeVersion,
    ContentPlanOutcome,
    ContentPlanVersion,
)

from benchmarks.phase6.evaluator import load_gold_prompts
from benchmarks.phase7.evaluator import (
    Phase7Evaluator,
    RenderObservation,
    load_attack_corpus,
)
from scripts.phase6_real_evaluation import load_deepseek_key, request_for_entry

GoldEntry = Mapping[str, object]
_ERROR_TYPE = re.compile(r"\b[A-Za-z][A-Za-z0-9_]*(?:Error|Exception)\b")


class EvaluationRenderer:
    def __init__(self, target: Phase7SandboxRenderer) -> None:
        self._target = target
        self.diagnostic_codes: list[str] = []

    def render(self, source_code: str, scene_class: str):  # type: ignore[no-untyped-def]
        result = self._target.render(source_code, scene_class)
        if not result.succeeded:
            self.diagnostic_codes.extend(sorted(set(_ERROR_TYPE.findall(result.diagnostic))))
        return result


class EvaluationRepository:
    def __init__(self, plan: ContentPlanVersion) -> None:
        self._plan = plan
        self.failure_codes: list[str] = []

    def load_input(self, request: CodeGenerationRequest) -> LoadedCodeGenerationInput:
        if request.content_plan_version_id != self._plan.id:
            raise RuntimeError("evaluation ContentPlan identity mismatch")
        return LoadedCodeGenerationInput(content_plan=self._plan)

    def load_category_policies(self) -> dict[CodeGenerationCategory, CategoryPolicy]:
        return {category: CategoryPolicy() for category in CodeGenerationCategory}

    def record_failed_attempt(self, request, **values) -> None:  # type: ignore[no-untyped-def]
        del request
        code = values.get("error_code")
        self.failure_codes.append(str(getattr(code, "value", code) or "missing_code"))

    def save_success(
        self,
        request: CodeGenerationRequest,
        *,
        response: CodeModelResponse,
        attempt_number: int,
        mode: CodeGenerationMode,
        prompt_template_version: str,
        provider_model: str | None,
    ) -> CodeVersion:
        del attempt_number
        import hashlib

        return CodeVersion(
            id=uuid5(NAMESPACE_URL, f"phase7-code:{request.content_plan_version_id}"),
            project_id=request.project_id,
            owner_id=request.owner_id,
            version=1,
            parent_version_id=None,
            created_at=datetime.now(timezone.utc),
            prompt_version_id=request.prompt_version_id,
            content_plan_version_id=request.content_plan_version_id,
            source_code=response.code,
            source_sha256=hashlib.sha256(response.code.encode("utf-8")).hexdigest(),
            scene_class=response.scene_class,
            engine="manimce",
            engine_version="0.21.0",
            category=request.category,
            generation_mode=mode,
            prompt_template_version=prompt_template_version,
            provider_model=provider_model,
            assumptions=response.assumptions,
        )


class RealPhase7Runner:
    def __init__(
        self,
        *,
        provider: DeepSeekProvider,
        renderer: Phase7SandboxRenderer,
    ) -> None:
        self._provider = provider
        self._renderer = renderer
        self.diagnostics: dict[str, tuple[str, ...]] = {}

    def __call__(self, entry: GoldEntry, repetition: int) -> RenderObservation:
        started = time.perf_counter()
        identifier = _required_string(entry, "id")
        stage = "content_plan"
        repository: EvaluationRepository | None = None
        renderer = EvaluationRenderer(self._renderer)
        try:
            plan = self._generate_plan(entry, repetition)
            stage = "code_generation"
            request = self._code_request(entry, plan, repetition)
            repository = EvaluationRepository(plan)
            response = CodeGenerationService(
                repository,
                self._provider,
                renderer,
            ).generate(request)
            version = response.code_version
            if version is None:
                raise RuntimeError("successful generation did not return a CodeVersion")
            stage = "quality_judge"
            try:
                math_score, visual_score = self._judge(entry, version.source_code)
            except (ContentPlanError, ValueError) as error:
                code = getattr(error, "code", None)
                safe_code = str(getattr(code, "value", code) or "invalid_quality_payload")
                self.diagnostics[identifier] = (
                    stage,
                    f"{type(error).__module__}.{type(error).__name__}",
                    safe_code,
                )
                math_score = visual_score = None
            return RenderObservation(
                first_render_succeeded=response.attempts_used == 1,
                final_render_succeeded=True,
                security_blocked=False,
                sandbox_invocations=max(1, response.attempts_used),
                math_score=math_score,
                visual_score=visual_score,
                attempts_used=response.attempts_used,
                duration_ms=(time.perf_counter() - started) * 1000,
                candidate_source=version.source_code,
                policy_state="active",
            )
        except (CodeGenerationError, ContentPlanError) as error:
            code = getattr(error, "code", None)
            details = tuple(getattr(error, "diagnostic_codes", ()))
            safe_code = str(getattr(code, "value", code) or "missing_code")
            self.diagnostics[identifier] = (
                stage,
                f"{type(error).__module__}.{type(error).__name__}",
                safe_code,
                *(repository.failure_codes if repository is not None else ()),
                *renderer.diagnostic_codes,
                *details,
            )
            return RenderObservation(
                first_render_succeeded=False,
                final_render_succeeded=False,
                security_blocked=(getattr(code, "value", code) == "security_policy_violation"),
                sandbox_invocations=0,
                math_score=None,
                visual_score=None,
                attempts_used=1,
                duration_ms=(time.perf_counter() - started) * 1000,
                error_code=str(getattr(code, "value", code) or "internal_error"),
                policy_state="active",
            )
        except Exception as error:
            self.diagnostics[identifier] = (
                stage,
                f"{type(error).__module__}.{type(error).__name__}",
            )
            return RenderObservation(
                first_render_succeeded=False,
                final_render_succeeded=False,
                security_blocked=False,
                sandbox_invocations=0,
                math_score=None,
                visual_score=None,
                attempts_used=0,
                duration_ms=(time.perf_counter() - started) * 1000,
                error_code="internal_error",
                policy_state="active",
            )

    def _generate_plan(self, entry: GoldEntry, repetition: int) -> ContentPlanVersion:
        request = request_for_entry(entry)
        source_prompt = _required_string(entry, "prompt")
        messages = build_content_plan_messages(source_prompt, request)
        last_error: ContentPlanError | None = None
        for attempt in (1, 2):
            try:
                result = self._provider.generate(messages)
                response = ContentPlanService._parse(result)
                response = validate_content_plan_response(response, request, source_prompt)
            except ContentPlanError as error:
                last_error = error
                retryable = error.retryable or isinstance(error, ContentPlanSemanticError)
                if retryable and attempt == 1:
                    continue
                raise
            if response.outcome is not ContentPlanOutcome.READY or response.plan is None:
                raise RuntimeError("gold prompt did not produce a ready ContentPlan")
            return ContentPlanVersion(
                id=uuid5(
                    NAMESPACE_URL,
                    f"phase7-plan:{_required_string(entry, 'id')}:{repetition}",
                ),
                project_id=request.project_id,
                owner_id=request.owner_id,
                version=1,
                parent_version_id=None,
                created_at=datetime.now(timezone.utc),
                **response.plan.model_dump(),
            )
        assert last_error is not None
        raise last_error

    @staticmethod
    def _code_request(
        entry: GoldEntry,
        plan: ContentPlanVersion,
        repetition: int,
    ) -> CodeGenerationRequest:
        identifier = _required_string(entry, "id")
        return CodeGenerationRequest(
            project_id=plan.project_id,
            owner_id=plan.owner_id,
            prompt_version_id=uuid5(
                NAMESPACE_URL, f"phase7-prompt:{identifier}:{repetition}"
            ),
            content_plan_version_id=plan.id,
            category=CodeGenerationCategory(_required_string(entry, "category")),
        )

    def _judge(self, entry: GoldEntry, source_code: str) -> tuple[int, int]:
        rubric = {
            "category": entry.get("category"),
            "teaching_goal": entry.get("teaching_goal"),
            "must_include": entry.get("must_include"),
            "must_avoid": entry.get("must_avoid"),
            "correctness_checks": entry.get("correctness_checks"),
            "expected_scene_structure": entry.get("expected_scene_structure"),
        }
        messages = (
            ProviderMessage(
                role="system",
                content=(
                    "Score the supplied rendered-successful Manim source against the rubric. "
                    "Return only strict JSON with integer math_score and visual_score from 0 to 5. "
                    "math_score measures mathematical correctness and required content. "
                    "The source has already rendered successfully in the real sandbox. "
                    "visual_score measures the frozen Phase 7 clarity rubric, not artistic "
                    "polish. Give visual_score 4 when the source has a readable title, at least "
                    "four visible teaching beats, deliberate spacing, and relevant highlighting; "
                    "formula scenes qualify with a central formula, step reasons, transforms and "
                    "Indicate, while function scenes qualify with labeled axes, a plotted curve, "
                    "formula label and at least two relevant points, regions, asymptotes or "
                    "parameter changes. Unicode formulas rendered with Text are valid and must "
                    "not be penalized merely for not using MathTex. Give 5 only for excellent "
                    "clarity. Give 3 or less when a required clarity element is actually absent."
                ),
            ),
            ProviderMessage(
                role="user",
                content=json.dumps(
                    {"rubric": rubric, "source_code": source_code},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ),
        )
        last_error: ContentPlanError | ValueError | None = None
        for attempt in (1, 2):
            try:
                result = self._provider.generate(messages)
                return _parse_quality_scores(result.content)
            except (ContentPlanError, ValueError) as error:
                last_error = error
                if attempt == 1:
                    continue
                raise
        assert last_error is not None
        raise last_error


def _parse_quality_scores(raw_response: str) -> tuple[int, int]:
    try:
        payload = json.loads(raw_response)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("quality judge returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("quality judge returned an invalid payload")
    scores = payload.get("math_score"), payload.get("visual_score")
    if not all(type(score) is int and 0 <= score <= 5 for score in scores):
        raise ValueError("quality judge scores are out of range")
    return scores


def _required_string(entry: GoldEntry, field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"gold entry requires non-empty {field}")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run redacted real Phase 7 evaluation")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--gold-set", type=Path, default=Path("eval/gold_prompts.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attack-output", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--limit", type=int, choices=range(1, 31))
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--repetitions", type=int, choices=(1, 3), default=1)
    parser.add_argument("--diagnostics", action="store_true")
    arguments = parser.parse_args(argv)

    import os

    os.environ["DEEPSEEK_API_KEY"] = load_deepseek_key(arguments.env_file)
    entries = load_gold_prompts(arguments.gold_set)
    if arguments.ids:
        requested = set(arguments.ids)
        entries = tuple(entry for entry in entries if entry["id"] in requested)
        if {entry["id"] for entry in entries} != requested:
            raise ValueError("one or more requested gold IDs were not found")
    if arguments.limit is not None:
        entries = entries[: arguments.limit]

    provider = DeepSeekProvider()
    renderer = Phase7SandboxRenderer(runtime_root=arguments.runtime_root)
    runner = RealPhase7Runner(provider=provider, renderer=renderer)
    evaluator = Phase7Evaluator(runner=runner)
    report = evaluator.evaluate(entries, repetitions=arguments.repetitions)
    evaluator.write_jsonl_report(arguments.output, report)

    attacks = load_attack_corpus(
        Path("benchmarks/phase7/fixtures/malicious_attack_corpus.v1.json")
    )
    attack_report = evaluator.evaluate_attacks(
        attacks,
        security_gate=validate_source_security,
    )
    evaluator.write_attack_jsonl_report(arguments.attack_output, attack_report)
    print(json.dumps(report.summary_dict(), ensure_ascii=False, sort_keys=True))
    print(json.dumps(attack_report.summary_dict(), ensure_ascii=False, sort_keys=True))
    if arguments.diagnostics:
        print(json.dumps({"diagnostics": runner.diagnostics}, sort_keys=True))
    if arguments.limit is not None or arguments.ids:
        return 0 if all(record.final_render_succeeded for record in report.records) else 1
    return 0 if evaluator.combined_gates_passed(report, attack_report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
