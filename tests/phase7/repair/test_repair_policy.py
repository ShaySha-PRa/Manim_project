from __future__ import annotations

from manim_workbench_api.code_generation.repair import (
    CategoryPolicyState,
    RepairAction,
    RepairOrchestrator,
    build_repair_messages,
)
from manim_workbench_contracts import CodeGenerationCategory, CodeGenerationErrorCode


def test_initial_generation_and_repair_budget_are_bounded_to_three_attempts() -> None:
    policy = RepairOrchestrator()
    category = CodeGenerationCategory.FORMULA_DERIVATION

    initial = policy.initial_decision(category)
    first_repair = policy.failure_decision(
        category, attempt_number=1, error_code=CodeGenerationErrorCode.COMPILE_FAILED
    )
    second_repair = policy.failure_decision(
        category, attempt_number=2, error_code=CodeGenerationErrorCode.RENDER_FAILED
    )
    exhausted = policy.failure_decision(
        category, attempt_number=3, error_code=CodeGenerationErrorCode.RENDER_FAILED
    )

    assert initial.action is RepairAction.GENERATE
    assert initial.attempt_number == 1
    assert first_repair.action is RepairAction.REPAIR
    assert first_repair.attempt_number == 2
    assert second_repair.action is RepairAction.REPAIR
    assert second_repair.attempt_number == 3
    assert exhausted.action is RepairAction.FAIL
    assert exhausted.error_code is CodeGenerationErrorCode.ATTEMPT_BUDGET_EXHAUSTED


def test_non_repairable_failure_matrix_never_spends_repair_budget() -> None:
    policy = RepairOrchestrator()
    category = CodeGenerationCategory.FUNCTION_VISUALIZATION

    non_repairable = (
        CodeGenerationErrorCode.SECURITY_POLICY_VIOLATION,
        CodeGenerationErrorCode.PROVIDER_AUTHENTICATION,
        CodeGenerationErrorCode.PROVIDER_CONFIGURATION,
        CodeGenerationErrorCode.INTERNAL_ERROR,
        CodeGenerationErrorCode.SANDBOX_RESOURCE_LIMIT,
        "cancelled",
    )

    for error_code in non_repairable:
        decision = policy.failure_decision(category, attempt_number=1, error_code=error_code)
        assert decision.action is RepairAction.FAIL
        assert decision.attempt_number == 1
        assert decision.include_candidate_source is False

    syntax = policy.failure_decision(
        category,
        attempt_number=1,
        error_code=CodeGenerationErrorCode.AST_PARSE_FAILED,
    )
    assert syntax.action is RepairAction.REPAIR
    assert syntax.include_candidate_source is False
    static_policy = policy.failure_decision(
        category,
        attempt_number=1,
        error_code=CodeGenerationErrorCode.STATIC_POLICY_REPAIRABLE,
    )
    assert static_policy.action is RepairAction.REPAIR
    assert static_policy.include_candidate_source is False


def test_category_quality_degradation_is_independent_and_security_escape_pauses_all() -> None:
    policy = RepairOrchestrator()
    formula = CodeGenerationCategory.FORMULA_DERIVATION
    function = CodeGenerationCategory.FUNCTION_VISUALIZATION

    assert policy.record_quality_round(formula, passed=False).state is CategoryPolicyState.ACTIVE
    assert policy.record_quality_round(formula, passed=False).state is CategoryPolicyState.DEGRADED
    assert policy.category_policy(function).state is CategoryPolicyState.ACTIVE
    assert policy.initial_decision(formula).action is RepairAction.DETERMINISTIC_TEMPLATE
    assert policy.initial_decision(function).action is RepairAction.GENERATE

    policy.record_security_escape()

    assert policy.category_policy(formula).state is CategoryPolicyState.PAUSED
    assert policy.category_policy(function).state is CategoryPolicyState.PAUSED
    assert policy.record_quality_round(function, passed=True).state is CategoryPolicyState.PAUSED
    assert policy.initial_decision(formula).action is RepairAction.PAUSE
    assert policy.initial_decision(function).action is RepairAction.PAUSE


def test_repair_messages_exclude_secrets_urls_and_absolute_paths() -> None:
    policy = RepairOrchestrator()
    decision = policy.failure_decision(
        CodeGenerationCategory.FORMULA_DERIVATION,
        attempt_number=1,
        error_code=CodeGenerationErrorCode.RENDER_FAILED,
    )
    messages = build_repair_messages(
        content_plan={"title": "Derivative", "scenes": [{"teaching_goal": "show slope"}]},
        decision=decision,
        candidate_source="from manim import Scene\nclass GeneratedScene(Scene): pass\n",
        diagnostic=(
            "Traceback /home/developer/projects/Manim_project/.env\n"
            "GET https://example.test/private?token=leak\n"
            "Authorization: Bearer very-secret-token\n"
            "DEEPSEEK_API_KEY=sk-1234567890abcdef\n"
            "line 12: ordinary render failure"
        ),
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert decision.action is RepairAction.REPAIR
    assert decision.template_metadata["template_version"] == "repair-v1"
    assert "ordinary render failure" in prompt
    assert "very-secret-token" not in prompt
    assert "sk-1234567890abcdef" not in prompt
    assert "https://example.test" not in prompt
    assert "/home/developer/projects" not in prompt
    assert "GeneratedScene" in prompt


def test_security_decision_cannot_be_used_to_build_a_repair_prompt() -> None:
    policy = RepairOrchestrator()
    decision = policy.failure_decision(
        CodeGenerationCategory.FORMULA_DERIVATION,
        attempt_number=1,
        error_code=CodeGenerationErrorCode.SECURITY_POLICY_VIOLATION,
    )

    try:
        build_repair_messages(
            content_plan={"title": "Derivative"},
            decision=decision,
            candidate_source="open('/home/developer/.env')",
            diagnostic="security violation",
        )
    except ValueError as error:
        assert "repair" in str(error)
    else:
        raise AssertionError("security violations must never form repair prompts")


def test_static_repair_prompt_regenerates_with_only_explicit_manim_imports() -> None:
    decision = RepairOrchestrator().failure_decision(
        CodeGenerationCategory.FUNCTION_VISUALIZATION,
        attempt_number=1,
        error_code=CodeGenerationErrorCode.STATIC_POLICY_REPAIRABLE,
    )

    messages = build_repair_messages(
        content_plan={"title": "Parabola"},
        decision=decision,
        diagnostic=(
            "Static policy fixes required: forbidden_lambda, unknown_name:Axes, "
            "unknown_attribute:coords_to_point"
        ),
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert '"scene_class":"GeneratedScene"' in prompt
    assert '"code":"..."' in prompt
    assert '"assumptions":[]' in prompt
    assert "Do not use Markdown fences" in prompt
    assert "from manim import" in prompt
    assert "do not use any other imports" in prompt
    assert "local named function" in prompt
    assert "Use `c2p`" in prompt
    assert 'font="Noto Sans CJK SC"' in prompt
    assert "Never put Chinese text inside MathTex" in prompt
    assert "PREVIOUS_CANDIDATE_SOURCE" not in prompt


def test_repair_prompt_turns_content_plan_duration_into_an_explicit_constraint() -> None:
    decision = RepairOrchestrator().failure_decision(
        CodeGenerationCategory.FORMULA_DERIVATION,
        attempt_number=1,
        error_code=CodeGenerationErrorCode.SCENE_STRUCTURE_INVALID,
    )

    messages = build_repair_messages(
        content_plan={"title": "Tangent", "target_duration_seconds": 60},
        decision=decision,
        diagnostic="duration_too_short: measured=24.0 threshold=54.0",
        candidate_source="from manim import Scene\nclass GeneratedScene(Scene): pass\n",
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "exactly 60 seconds" in prompt
    assert "54.0 to 66.0 seconds" in prompt
    assert "at least 15 active self.play calls" in prompt
    assert "each individual self.play run_time at or below 4 seconds" in prompt
    assert "Do not use one long wait" in prompt
