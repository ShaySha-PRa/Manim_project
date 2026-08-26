from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from manim_workbench_api.code_generation.errors import CodeGenerationError
from manim_workbench_api.code_generation.gallery_fixtures import (
    fixed_in_frame_storyboard,
    opening_manim_formula_storyboard,
)
from manim_workbench_api.code_generation.models import (
    CandidateRenderResult,
    LoadedCodeGenerationInput,
)
from manim_workbench_api.code_generation.repair import CategoryPolicy
from manim_workbench_api.code_generation.service import CodeGenerationService
from manim_workbench_api.content_plans.errors import ContentPlanError, ContentPlanErrorCode
from manim_workbench_api.content_plans.models import ProviderResult
from manim_workbench_contracts import (
    Audience,
    CodeGenerationCategory,
    CodeGenerationErrorCode,
    CodeGenerationMode,
    CodeGenerationOutcome,
    CodeGenerationRequest,
    CodeModelResponse,
    CodeVersion,
    ContentPlanScene,
    ContentPlanVersion,
    DerivationStyle,
    FormulaStep,
    Language,
)
from manim_workbench_contracts.ir import SceneStoryboard

VALID_SOURCE = (
    "from manim import Scene, Text, Write\n\n"
    "class GeneratedScene(Scene):\n"
    "    def construct(self):\n"
    "        formula = Text('y=kx', font='Noto Sans CJK SC')\n"
    "        self.play(Write(formula), run_time=60.0)\n"
)

SHORT_SOURCE = (
    "from manim import Scene, Text, Write\n\n"
    "class GeneratedScene(Scene):\n"
    "    def construct(self):\n"
    "        formula = Text('y=kx', font='Noto Sans CJK SC')\n"
    "        self.play(Write(formula), run_time=4.0)\n"
)


def content_plan() -> ContentPlanVersion:
    return ContentPlanVersion(
        id=uuid4(),
        project_id=uuid4(),
        owner_id=uuid4(),
        version=1,
        parent_version_id=None,
        created_at=datetime.now(timezone.utc),
        schema_version="1.1",
        title="一次函数",
        audience=Audience.HIGH_SCHOOL,
        language=Language.ZH_CN,
        target_duration_seconds=60,
        derivation_style=DerivationStyle.VISUAL_INTUITION,
        explicit_assumptions=(),
        ambiguities=(),
        scenes=(
            ContentPlanScene(
                scene_number=1,
                teaching_goal="观察斜率",
                formula_steps=(FormulaStep(expression="y=kx", explanation="改变 k。"),),
                visual_intent="显示坐标轴。",
                narration_placeholder="比较斜率。",
            ),
        ),
    )


def request_for(
    plan: ContentPlanVersion,
    category: CodeGenerationCategory = CodeGenerationCategory.FUNCTION_VISUALIZATION,
) -> CodeGenerationRequest:
    return CodeGenerationRequest(
        project_id=plan.project_id,
        owner_id=plan.owner_id,
        prompt_version_id=uuid4(),
        content_plan_version_id=plan.id,
        category=category,
    )


def model_json(source: str = VALID_SOURCE) -> str:
    return json.dumps(
        {"scene_class": "GeneratedScene", "code": source, "assumptions": []},
        ensure_ascii=False,
    )


class FakeProvider:
    def __init__(self, responses: list[str | Exception]) -> None:
        self.responses = iter(responses)
        self.calls = 0
        self.messages = []

    def generate(self, messages):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.messages.append(messages)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return ProviderResult(
            content=response,
            finish_reason="stop",
            request_id=f"request-{self.calls}",
            model="deepseek-v4-flash",
        )


class FakeRenderer:
    def __init__(self, results: list[CandidateRenderResult]) -> None:
        self.results = iter(results)
        self.calls = 0

    def render(self, source_code: str, scene_class: str) -> CandidateRenderResult:
        assert source_code.startswith("from manim")
        assert scene_class == "GeneratedScene"
        self.calls += 1
        return next(self.results)


class FakeRepository:
    def __init__(self, plan: ContentPlanVersion) -> None:
        self.plan = plan
        self.failures = []
        self.saved: list[dict[str, object]] = []

    def load_input(self, request: CodeGenerationRequest) -> LoadedCodeGenerationInput:
        assert request.content_plan_version_id == self.plan.id
        return LoadedCodeGenerationInput(content_plan=self.plan)

    def load_category_policies(self):  # type: ignore[no-untyped-def]
        return {category: CategoryPolicy() for category in CodeGenerationCategory}

    def record_failed_attempt(self, request, **values):  # type: ignore[no-untyped-def]
        self.failures.append(values)

    def save_success(self, request, **values):  # type: ignore[no-untyped-def]
        self.saved.append(values)
        response: CodeModelResponse = values["response"]
        mode: CodeGenerationMode = values["mode"]
        return CodeVersion(
            id=uuid4(),
            project_id=request.project_id,
            owner_id=request.owner_id,
            version=1,
            parent_version_id=None,
            created_at=datetime.now(timezone.utc),
            prompt_version_id=request.prompt_version_id,
            content_plan_version_id=request.content_plan_version_id,
            source_code=response.code,
            source_sha256="a" * 64,
            scene_class=response.scene_class,
            engine="manimce",
            engine_version="0.21.0",
            category=request.category,
            generation_mode=mode,
        )


def legacy_service(
    repository: FakeRepository, provider: FakeProvider, renderer: FakeRenderer
) -> CodeGenerationService:
    return CodeGenerationService(
        repository,
        provider,
        renderer,
        allow_legacy_free_python=True,
    )


def test_success_is_persisted_only_after_security_preflight_and_sandbox() -> None:
    plan = content_plan()
    repository = FakeRepository(plan)
    provider = FakeProvider([model_json()])
    renderer = FakeRenderer([CandidateRenderResult(succeeded=True)])

    response = legacy_service(repository, provider, renderer).generate(request_for(plan))

    assert response.outcome is CodeGenerationOutcome.READY
    assert response.attempts_used == 1
    assert provider.calls == renderer.calls == len(repository.saved) == 1
    assert repository.failures == []


def test_default_teaching_path_compiles_storyboard_without_free_python_provider() -> None:
    plan = content_plan()
    repository = FakeRepository(plan)
    provider = FakeProvider([])
    renderer = FakeRenderer([CandidateRenderResult(succeeded=True)])

    response = CodeGenerationService(repository, provider, renderer).generate(request_for(plan))

    assert response.outcome is CodeGenerationOutcome.READY
    assert response.mode is CodeGenerationMode.COMPILED_IR
    assert response.attempts_used == 1
    assert provider.calls == 0
    assert renderer.calls == 1
    assert repository.saved[0]["mode"] is CodeGenerationMode.COMPILED_IR
    source = repository.saved[0]["response"].code
    assert "Axes(" in source
    assert "lambda" not in source


def test_default_geometry_path_requires_a_validated_storyboard_instead_of_placeholder() -> None:
    plan = content_plan()
    repository = FakeRepository(plan)
    provider = FakeProvider([])
    renderer = FakeRenderer([])

    with pytest.raises(CodeGenerationError) as caught:
        CodeGenerationService(repository, provider, renderer).generate(
            request_for(plan, CodeGenerationCategory.GEOMETRY_PROOF)
        )

    assert caught.value.code is CodeGenerationErrorCode.INVALID_MODEL_RESPONSE
    assert "requires a validated SceneStoryboard" in str(caught.value)
    assert provider.calls == 0
    assert renderer.calls == 0
    assert repository.saved == []


def test_teaching_service_exposes_every_compiled_segment_without_rendering_or_truncation() -> None:
    base_plan = content_plan()
    formula = opening_manim_formula_storyboard().steps[0]
    surface = fixed_in_frame_storyboard().steps[0]
    summary = formula.model_copy(update={"goal": "Summarize the result"})
    plan = base_plan.model_copy(
        update={
            "schema_version": "1.6",
            "storyboard": SceneStoryboard(
                target_duration_seconds=48,
                steps=(formula, surface, summary),
            ),
        }
    )
    repository = FakeRepository(plan)
    renderer = FakeRenderer([])
    service = CodeGenerationService(repository, FakeProvider([]), renderer)

    program = service.compile_program(request_for(plan, CodeGenerationCategory.MIXED))

    assert [segment.scene_base for segment in program.segments] == [
        "Scene",
        "ThreeDScene",
        "Scene",
    ]
    assert renderer.calls == 0
    assert repository.saved == []


def test_legacy_teaching_response_rejects_multi_segment_program_explicitly() -> None:
    base_plan = content_plan()
    formula = opening_manim_formula_storyboard().steps[0]
    surface = fixed_in_frame_storyboard().steps[0]
    plan = base_plan.model_copy(
        update={
            "schema_version": "1.6",
            "storyboard": SceneStoryboard(
                target_duration_seconds=48,
                steps=(formula, surface, formula),
            ),
        }
    )
    repository = FakeRepository(plan)
    renderer = FakeRenderer([])

    with pytest.raises(CodeGenerationError, match="ProgramRenderService"):
        CodeGenerationService(repository, FakeProvider([]), renderer).generate(
            request_for(plan, CodeGenerationCategory.MIXED)
        )

    assert renderer.calls == 0
    assert repository.saved == []


def test_short_timeline_uses_bounded_repair_before_render_or_persistence() -> None:
    plan = content_plan()
    repository = FakeRepository(plan)
    provider = FakeProvider([model_json(SHORT_SOURCE), model_json()])
    renderer = FakeRenderer([CandidateRenderResult(succeeded=True)])

    response = legacy_service(repository, provider, renderer).generate(request_for(plan))

    assert response.outcome is CodeGenerationOutcome.READY
    assert response.attempts_used == 2
    assert provider.calls == 2
    assert renderer.calls == 1
    assert len(repository.failures) == 1
    assert repository.failures[0]["error_code"] is CodeGenerationErrorCode.SCENE_STRUCTURE_INVALID
    repair_prompt = provider.messages[1][1].content
    assert "duration_too_short" in repair_prompt
    assert "measured=4.0" in repair_prompt
    assert "54.0 to 66.0 seconds" in repair_prompt
    assert "exactly 60 seconds" in repair_prompt
    assert "PREVIOUS_CANDIDATE_SOURCE" in repair_prompt


def test_exhausted_repair_budget_uses_quality_checked_deterministic_template() -> None:
    plan = content_plan()
    repository = FakeRepository(plan)
    provider = FakeProvider([model_json(SHORT_SOURCE)] * 3)
    renderer = FakeRenderer([CandidateRenderResult(succeeded=True)])

    response = legacy_service(repository, provider, renderer).generate(request_for(plan))

    assert response.outcome is CodeGenerationOutcome.DEGRADED
    assert response.attempts_used == 3
    assert provider.calls == 3
    assert renderer.calls == 1
    assert len(repository.failures) == 3
    assert len(repository.saved) == 1
    saved = repository.saved[0]
    assert saved["mode"] is CodeGenerationMode.DETERMINISTIC_TEMPLATE
    assert saved["attempt_number"] == 3
    candidate: CodeModelResponse = saved["response"]
    assert "run_time=" in candidate.code
    assert "self.wait(" in candidate.code


def test_two_transient_provider_retries_do_not_consume_repair_budget() -> None:
    plan = content_plan()
    repository = FakeRepository(plan)
    provider = FakeProvider(
        [
            ContentPlanError(
                ContentPlanErrorCode.PROVIDER_UNAVAILABLE,
                "temporary transport failure",
            ),
            ContentPlanError(
                ContentPlanErrorCode.PROVIDER_RATE_LIMITED,
                "temporary rate limit",
            ),
            model_json(),
        ]
    )
    renderer = FakeRenderer([CandidateRenderResult(succeeded=True)])

    response = legacy_service(repository, provider, renderer).generate(request_for(plan))

    assert response.attempts_used == 1
    assert provider.calls == 3
    assert renderer.calls == 1
    assert repository.failures == []


def test_security_failure_never_enters_sandbox_or_repair() -> None:
    plan = content_plan()
    repository = FakeRepository(plan)
    provider = FakeProvider([model_json("from manim import Scene\nopen('/etc/passwd')")])
    renderer = FakeRenderer([])

    with pytest.raises(CodeGenerationError) as caught:
        legacy_service(repository, provider, renderer).generate(request_for(plan))

    assert caught.value.code is CodeGenerationErrorCode.SECURITY_POLICY_VIOLATION
    assert provider.calls == 1
    assert renderer.calls == 0
    assert len(repository.failures) == 1


def test_render_failure_uses_at_most_two_repairs_then_persists() -> None:
    plan = content_plan()
    repository = FakeRepository(plan)
    provider = FakeProvider([model_json(), model_json()])
    renderer = FakeRenderer(
        [
            CandidateRenderResult(
                succeeded=False,
                error_code="render_failed",
                diagnostic="ordinary render failure",
            ),
            CandidateRenderResult(succeeded=True),
        ]
    )

    response = legacy_service(repository, provider, renderer).generate(request_for(plan))

    assert response.outcome is CodeGenerationOutcome.READY
    assert response.attempts_used == 2
    assert provider.calls == renderer.calls == 2
    assert len(repository.failures) == 1
    assert repository.failures[0]["error_code"] is CodeGenerationErrorCode.RENDER_FAILED
    assert "APPROVED_SANITIZED_DIAGNOSTIC" in provider.messages[1][1].content


def test_unknown_safe_api_and_lambda_are_repaired_without_entering_sandbox() -> None:
    plan = content_plan()
    repository = FakeRepository(plan)
    missing_import = (
        "from manim import Scene\nclass GeneratedScene(Scene):\n"
        "    def construct(self):\n        graph = Axes().plot(lambda x: x)\n"
    )
    provider = FakeProvider([model_json(missing_import), model_json()])
    renderer = FakeRenderer([CandidateRenderResult(succeeded=True)])

    response = legacy_service(repository, provider, renderer).generate(request_for(plan))

    assert response.attempts_used == 2
    assert provider.calls == 2
    assert renderer.calls == 1
    assert repository.failures[0]["error_code"] is (
        CodeGenerationErrorCode.STATIC_POLICY_REPAIRABLE
    )
    repair_prompt = provider.messages[1][1].content
    assert "forbidden_lambda" in repair_prompt
    assert "PREVIOUS_CANDIDATE_SOURCE" not in repair_prompt


def test_missing_allowlisted_manim_import_is_completed_before_first_render() -> None:
    plan = content_plan()
    repository = FakeRepository(plan)
    missing_up = (
        "from manim import Scene, Text, Write\nclass GeneratedScene(Scene):\n"
        "    def construct(self):\n        title = Text('y=kx').to_edge(UP)\n"
        "        self.play(Write(title), run_time=60.0)\n"
    )
    provider = FakeProvider([model_json(missing_up)])
    renderer = FakeRenderer([CandidateRenderResult(succeeded=True)])

    response = legacy_service(repository, provider, renderer).generate(request_for(plan))

    assert response.attempts_used == 1
    assert provider.calls == renderer.calls == 1
    assert repository.failures == []
    assert "UP" in repository.saved[0]["response"].code.splitlines()[0]


def test_low_risk_scene_structure_drift_uses_source_free_repair() -> None:
    plan = content_plan()
    repository = FakeRepository(plan)
    extra_method = (
        "from manim import Scene\nclass GeneratedScene(Scene):\n"
        "    def helper(self):\n        pass\n"
        "    def construct(self):\n        pass\n"
    )
    provider = FakeProvider([model_json(extra_method), model_json()])
    renderer = FakeRenderer([CandidateRenderResult(succeeded=True)])

    response = legacy_service(repository, provider, renderer).generate(request_for(plan))

    assert response.attempts_used == 2
    assert repository.failures[0]["error_code"] is (
        CodeGenerationErrorCode.STATIC_POLICY_REPAIRABLE
    )
    assert "invalid_scene_structure" in provider.messages[1][1].content
    assert "PREVIOUS_CANDIDATE_SOURCE" not in provider.messages[1][1].content


def test_three_render_failures_exhaust_budget_without_persisting() -> None:
    plan = content_plan()
    repository = FakeRepository(plan)
    provider = FakeProvider([model_json(), model_json(), model_json()])
    renderer = FakeRenderer(
        [CandidateRenderResult(False, "render_failed", "failure") for _ in range(4)]
    )

    with pytest.raises(CodeGenerationError) as caught:
        legacy_service(repository, provider, renderer).generate(request_for(plan))

    assert caught.value.code is CodeGenerationErrorCode.ATTEMPT_BUDGET_EXHAUSTED
    assert provider.calls == 3
    assert renderer.calls == 4
    assert repository.saved == []


def test_third_latex_failure_uses_validated_text_degradation() -> None:
    plan = content_plan()
    repository = FakeRepository(plan)
    latex_source = (
        "from manim import MathTex, Scene, Write\nclass GeneratedScene(Scene):\n"
        "    def construct(self):\n        equation = MathTex(r'y=kx')\n"
        "        self.play(Write(equation), run_time=60.0)\n"
    )
    provider = FakeProvider([model_json(latex_source) for _ in range(3)])
    renderer = FakeRenderer(
        [
            CandidateRenderResult(False, "render_failed", "latex error converting to dvi"),
            CandidateRenderResult(False, "render_failed", "latex error converting to dvi"),
            CandidateRenderResult(False, "render_failed", "latex error converting to dvi"),
            CandidateRenderResult(succeeded=True),
        ]
    )

    response = legacy_service(repository, provider, renderer).generate(request_for(plan))

    assert response.outcome is CodeGenerationOutcome.DEGRADED
    assert response.mode is CodeGenerationMode.DETERMINISTIC_TEMPLATE
    assert response.attempts_used == 3
    assert provider.calls == 3
    assert renderer.calls == 4
    assert len(repository.failures) == 2
    assert repository.saved[0]["mode"] is CodeGenerationMode.DETERMINISTIC_TEMPLATE
    assert "MathTex(" not in repository.saved[0]["response"].code
