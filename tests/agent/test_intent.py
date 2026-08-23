from manim_workbench_api.agent.intent_resolver import (
    INTENT_SYSTEM_PROMPT,
    fill_intent_from_provider,
    intent_from_llm_json,
    resolve_intent,
)
from manim_workbench_api.agent.orchestrator import run_agent
from manim_workbench_api.content_plans.models import ProviderMessage, ProviderResult
from manim_workbench_contracts.intent import (
    AgentRunOutcome,
    IntentDomain,
    IntentSpec,
    ToolNeed,
    ToolOp,
)


class _FakeIntentProvider:
    def __init__(self, content: str) -> None:
        self.content = content
        self.messages: tuple[ProviderMessage, ...] | None = None

    def generate(self, messages: tuple[ProviderMessage, ...]) -> ProviderResult:
        self.messages = messages
        return ProviderResult(content=self.content, model="fake-intent")


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


def test_llm_csv_params_are_derived_from_explicit_prompt_time_only() -> None:
    base = IntentSpec(
        domain=IntentDomain.DATA_ANALYSIS,
        goal="show anomaly",
        tools_needed=(ToolNeed(op=ToolOp.CSV_ANOMALY, params={"center": 0}),),
    ).model_dump_json()
    without_time = fill_intent_from_provider(
        _FakeIntentProvider(base),
        "展示 timestamp、temperature、pressure 并自动突出异常",
        csv_text="timestamp,temperature,pressure\n0,1,2\n",
    )
    assert without_time.tools_needed[0].params == {}
    with_time = fill_intent_from_provider(
        _FakeIntentProvider(base),
        "突出 350 秒附近异常",
        csv_text="time,temperature,pressure\n350,1,2\n",
    )
    assert with_time.tools_needed[0].params == {"center": 350.0}
    with_time_assignment = fill_intent_from_provider(
        _FakeIntentProvider(base),
        "标记 time=2 的异常点",
        csv_text="time,temperature,pressure\n2,1,2\n",
    )
    assert with_time_assignment.tools_needed[0].params == {"center": 2.0}


def test_unknown_prompt_needs_confirmation() -> None:
    intent = resolve_intent("随便讲一个没见过的科研现象")
    assert intent.needs_confirmation is True
    result = run_agent("随便讲一个没见过的科研现象")
    assert result.outcome is AgentRunOutcome.NEEDS_CONFIRMATION


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
    try:
        intent_from_llm_json('{"from manim": true}')
    except ValueError as error:
        assert "Manim" in str(error) or "JSON" in str(error) or "IntentSpec" in str(error)
    else:
        raise AssertionError("Manim Python must be rejected")


def test_paper_prompt_needs_confirmation_without_parser() -> None:
    intent = resolve_intent("根据上传论文中的动力学方程和实验 CSV，模拟模型并与实验数据做动画对比")
    assert intent.domain is IntentDomain.SCIENTIFIC_REPRODUCTION
    assert intent.needs_confirmation is True
    result = run_agent("根据上传论文中的动力学方程和实验 CSV 对比")
    assert result.outcome is AgentRunOutcome.NEEDS_CONFIRMATION


def test_llm_provider_fills_intent_spec_only() -> None:
    payload = IntentSpec(
        domain=IntentDomain.MATH_SIGNAL,
        goal="show Fourier convergence and Gibbs overshoot",
        tools_needed=(),
    ).model_dump_json()
    provider = _FakeIntentProvider(payload)
    intent = fill_intent_from_provider(provider, "展示傅里叶级数逐渐逼近方波，并放大 Gibbs 现象")
    assert intent.domain is IntentDomain.MATH_SIGNAL
    assert provider.messages is not None
    assert provider.messages[0].content == INTENT_SYSTEM_PROMPT
    assert "from manim" not in provider.messages[0].content.lower()
    result = run_agent(
        "展示傅里叶级数逐渐逼近方波，并放大 Gibbs 现象",
        provider=provider,
    )
    assert result.intent is not None
    assert result.intent.domain is IntentDomain.MATH_SIGNAL


def test_intent_prompt_spells_out_the_strict_json_shape() -> None:
    assert 'schema_version must be the JSON string "1.0", not a number' in INTENT_SYSTEM_PROMPT
    assert "tools_needed must be an array of objects shaped exactly as" in INTENT_SYSTEM_PROMPT
    assert "never return tool names as bare strings" in INTENT_SYSTEM_PROMPT
    assert "evaluate expressions such as 8/3" in INTENT_SYSTEM_PROMPT
    assert "never add a top-level parameters field" in INTENT_SYSTEM_PROMPT
    assert "lorenz_ensemble allows only delta" in INTENT_SYSTEM_PROMPT
    assert "Never return arrays, objects, initial_conditions" in INTENT_SYSTEM_PROMPT
    assert "include center only when the user explicitly supplies a numeric time" in (
        INTENT_SYSTEM_PROMPT
    )


def test_invalid_llm_json_needs_confirmation() -> None:
    result = run_agent("展示傅里叶级数", provider=_FakeIntentProvider("not-json"))
    assert result.outcome is AgentRunOutcome.NEEDS_CONFIRMATION
