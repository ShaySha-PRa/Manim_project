"""IntentResolver → ScientificPlanner → ToolExecutor → VisualDirector → IR Validator."""

from __future__ import annotations

from pathlib import Path

from manim_workbench_contracts import (
    AgentEvent,
    AgentRunOutcome,
    AgentRunResponse,
    IntentSpec,
    ToolRun,
)

from manim_workbench_api.agent.intent_resolver import resolve_intent
from manim_workbench_api.agent.ir_validator import IrValidationError, validate_animation_ir
from manim_workbench_api.agent.scientific_planner import plan_tools
from manim_workbench_api.agent.visual_director import direct_ir
from manim_workbench_api.compiler.manim import UnsupportedFeature, compile_animation_ir
from manim_workbench_api.tools.registry import invoke


def run_agent(
    prompt: str,
    *,
    csv_text: str | None = None,
    output_root: Path | None = None,
) -> AgentRunResponse:
    events: list[AgentEvent] = [
        AgentEvent(stage="intent_resolver", status="started", message="解析一句话意图")
    ]
    intent = resolve_intent(prompt, csv_text=csv_text)
    events.append(
        AgentEvent(stage="intent_resolver", status="succeeded", message=intent.domain.value)
    )
    if intent.needs_confirmation:
        return AgentRunResponse(
            outcome=AgentRunOutcome.NEEDS_CONFIRMATION,
            intent=intent,
            events=tuple(events),
            message="科学意图存在歧义，请确认领域后再生成。",
        )
    if intent.asset_required:
        return AgentRunResponse(
            outcome=AgentRunOutcome.ASSET_REQUIRED,
            intent=intent,
            events=tuple(events),
            error_code="asset_required",
            message="缺少 CSV 资产，拒绝伪造科研数据。",
        )
    needs = plan_tools(intent)
    events.append(
        AgentEvent(stage="scientific_planner", status="succeeded", message=f"{len(needs)} tools")
    )
    tool_runs: list[ToolRun] = []
    for need in needs:
        events.append(AgentEvent(stage="tool_executor", status="started", message=need.op.value))
        tool_runs.append(
            invoke(need.op, need.params, input_text=csv_text, output_root=output_root)
        )
        events.append(
            AgentEvent(stage="tool_executor", status="succeeded", message=need.op.value)
        )
    ir = direct_ir(intent, tuple(tool_runs))
    events.append(AgentEvent(stage="visual_director", status="succeeded", message=ir.pattern.value))
    try:
        validate_animation_ir(ir, tuple(tool_runs))
    except IrValidationError as error:
        events.append(AgentEvent(stage="ir_validator", status="failed", message=str(error)))
        return AgentRunResponse(
            outcome=AgentRunOutcome.FAILED,
            intent=intent,
            tool_runs=tuple(tool_runs),
            animation_ir=ir,
            events=tuple(events),
            error_code="ir_invalid",
            message=str(error),
        )
    events.append(AgentEvent(stage="ir_validator", status="succeeded", message="AnimationIR 2.0"))
    try:
        compile_animation_ir(ir, tuple(tool_runs))
    except UnsupportedFeature as error:
        events.append(AgentEvent(stage="compiler", status="failed", message=str(error)))
        return AgentRunResponse(
            outcome=AgentRunOutcome.FAILED,
            intent=intent,
            tool_runs=tuple(tool_runs),
            animation_ir=ir,
            events=tuple(events),
            error_code="unsupported_feature",
            message=str(error),
        )
    events.append(AgentEvent(stage="compiler", status="succeeded", message="deterministic manim"))
    return AgentRunResponse(
        outcome=AgentRunOutcome.READY,
        intent=intent,
        tool_runs=tuple(tool_runs),
        animation_ir=ir,
        events=tuple(events),
    )


def describe_intent(intent: IntentSpec) -> str:
    return f"{intent.domain.value}: {intent.goal}"
