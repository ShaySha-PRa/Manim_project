from manim_workbench_api.agent.intent_resolver import intent_from_llm_json, resolve_intent
from manim_workbench_api.agent.orchestrator import run_agent
from manim_workbench_contracts.intent import AgentRunOutcome, IntentDomain, IntentSpec, ToolOp


def test_wave_prompt_resolves_to_physics_intent() -> None:
    intent = resolve_intent("展示二维波动方程中两个波包碰撞后的干涉过程")
    assert intent.domain is IntentDomain.PHYSICS_WAVE
    assert intent.tools_needed[0].op is ToolOp.WAVE2D_SUPERPOSITION
    assert intent.needs_confirmation is False


def test_csv_without_asset_is_required() -> None:
    intent = resolve_intent("从上传 CSV 展示 temperature/pressure 演化，并突出 350 秒附近异常")
    assert intent.asset_required is True
    result = run_agent("从上传 CSV 展示 temperature 异常")
    assert result.outcome is AgentRunOutcome.ASSET_REQUIRED
    assert result.error_code == "asset_required"


def test_llm_json_must_be_intent_spec_only() -> None:
    spec = intent_from_llm_json(
        IntentSpec(
            domain=IntentDomain.PHYSICS_WAVE,
            goal="two packets",
            tools_needed=(),
        ).model_dump_json()
    )
    assert spec.domain is IntentDomain.PHYSICS_WAVE
    try:
        intent_from_llm_json("```json\n{}\n```")
    except ValueError as error:
        assert "fenced" in str(error)
    else:
        raise AssertionError("fenced model output must be rejected")
