"""IntentResolver → tools → AnimationIR → compiler → critic → at most one IR repair."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from manim_workbench_contracts import (
    AgentEvent,
    AgentRunOutcome,
    AgentRunResponse,
    AssetMime,
    IntentSpec,
    ToolRun,
)
from sqlalchemy import Engine

from manim_workbench_api.agent.intent_resolver import IntentJsonProvider, resolve_intent
from manim_workbench_api.agent.ir_repair import repair_animation_ir
from manim_workbench_api.agent.ir_validator import IrValidationError, validate_animation_ir
from manim_workbench_api.agent.scientific_planner import plan_tools
from manim_workbench_api.agent.visual_director import direct_ir
from manim_workbench_api.assets.scientific import AssetIngestError, ingest_document
from manim_workbench_api.assets.versions import persist_asset_version
from manim_workbench_api.compiler.base import CompiledProgram
from manim_workbench_api.compiler.manim import UnsupportedFeature, compile_animation_ir
from manim_workbench_api.quality.semantic.critic import CriticJsonProvider, evaluate_expression
from manim_workbench_api.tools.registry import invoke


@dataclass(frozen=True, slots=True)
class AgentExecution:
    response: AgentRunResponse
    compiled_program: CompiledProgram | None


def run_agent(
    prompt: str,
    *,
    target_duration_seconds: float | None = None,
    csv_text: str | None = None,
    paper_text: str | None = None,
    output_root: Path | None = None,
    provider: IntentJsonProvider | None = None,
    critic_provider: CriticJsonProvider | None = None,
    engine: Engine | None = None,
    owner_id: UUID | None = None,
    project_id: UUID | None = None,
    intent_assumptions: tuple[str, ...] = (),
) -> AgentRunResponse:
    return run_agent_with_program(
        prompt,
        target_duration_seconds=target_duration_seconds,
        csv_text=csv_text,
        paper_text=paper_text,
        output_root=output_root,
        provider=provider,
        critic_provider=critic_provider,
        engine=engine,
        owner_id=owner_id,
        project_id=project_id,
        intent_assumptions=intent_assumptions,
    ).response


def run_agent_with_program(
    prompt: str,
    *,
    target_duration_seconds: float | None = None,
    csv_text: str | None = None,
    paper_text: str | None = None,
    output_root: Path | None = None,
    provider: IntentJsonProvider | None = None,
    critic_provider: CriticJsonProvider | None = None,
    engine: Engine | None = None,
    owner_id: UUID | None = None,
    project_id: UUID | None = None,
    intent_assumptions: tuple[str, ...] = (),
) -> AgentExecution:
    events: list[AgentEvent] = [
        AgentEvent(stage="intent_resolver", status="started", message="解析一句话意图")
    ]
    intent = resolve_intent(prompt, csv_text=csv_text, paper_text=paper_text, provider=provider)
    if intent_assumptions:
        intent = intent.model_copy(
            update={"assumptions": tuple(dict.fromkeys((*intent.assumptions, *intent_assumptions)))}
        )
    if target_duration_seconds is not None:
        if not 0 < target_duration_seconds <= 180:
            raise ValueError("target_duration_seconds must be in the range (0, 180]")
        intent = intent.model_copy(
            update={"output_duration_seconds": float(target_duration_seconds)}
        )
    events.append(
        AgentEvent(stage="intent_resolver", status="succeeded", message=intent.domain.value)
    )
    if paper_text and paper_text.strip() and engine is not None:
        persist_asset_version(
            engine,
            ingest_document(paper_text.encode("utf-8"), mime=AssetMime.TEXT),
            owner_id=owner_id,
            project_id=project_id,
        )
    if intent.needs_confirmation:
        return AgentExecution(
            response=AgentRunResponse(
                outcome=AgentRunOutcome.NEEDS_CONFIRMATION,
                intent=intent,
                events=tuple(events),
                message="科学意图存在歧义，请确认领域后再生成。",
            ),
            compiled_program=None,
        )
    if intent.asset_required:
        kind = intent.asset_kind or "csv"
        return AgentExecution(
            response=AgentRunResponse(
                outcome=AgentRunOutcome.ASSET_REQUIRED,
                intent=intent,
                events=tuple(events),
                error_code="asset_required",
                message=f"缺少 {kind} 资产，拒绝伪造科研数据。",
            ),
            compiled_program=None,
        )
    needs = plan_tools(intent)
    events.append(
        AgentEvent(stage="scientific_planner", status="succeeded", message=f"{len(needs)} tools")
    )
    tool_runs: list[ToolRun] = []
    for need in needs:
        events.append(AgentEvent(stage="tool_executor", status="started", message=need.op.value))
        try:
            tool_runs.append(
                invoke(
                    need.op,
                    need.params,
                    input_text=csv_text,
                    output_root=output_root,
                    engine=engine,
                    owner_id=owner_id,
                    project_id=project_id,
                )
            )
        except AssetIngestError as error:
            events.append(AgentEvent(stage="tool_executor", status="failed", message=str(error)))
            return AgentExecution(
                response=AgentRunResponse(
                    outcome=AgentRunOutcome.FAILED,
                    intent=intent,
                    events=tuple(events),
                    error_code="asset_invalid",
                    message=str(error),
                ),
                compiled_program=None,
            )
        events.append(AgentEvent(stage="tool_executor", status="succeeded", message=need.op.value))
    ir = direct_ir(intent, tuple(tool_runs))
    events.append(AgentEvent(stage="visual_director", status="succeeded", message=ir.pattern.value))
    try:
        validate_animation_ir(ir, tuple(tool_runs))
        compiled = compile_animation_ir(ir, tuple(tool_runs))
    except (IrValidationError, UnsupportedFeature) as error:
        stage = "ir_validator" if isinstance(error, IrValidationError) else "compiler"
        events.append(AgentEvent(stage=stage, status="failed", message=str(error)))
        return AgentExecution(
            response=AgentRunResponse(
                outcome=AgentRunOutcome.FAILED,
                intent=intent,
                tool_runs=tuple(tool_runs),
                animation_ir=ir,
                events=tuple(events),
                error_code=(
                    "ir_invalid"
                    if isinstance(error, IrValidationError)
                    else "unsupported_feature"
                ),
                message=str(error),
            ),
            compiled_program=None,
        )
    events.append(AgentEvent(stage="compiler", status="succeeded", message="deterministic manim"))
    source = _compiled_program_source(compiled)
    critic = evaluate_expression(ir, tuple(tool_runs), source, provider=critic_provider)
    events.append(
        AgentEvent(
            stage="critic",
            status="succeeded",
            message=f"expression={critic.expression_score}",
        )
    )
    repair_count = 0
    if any(item.repairable for item in critic.findings):
        repaired = repair_animation_ir(ir, critic.findings)
        try:
            validate_animation_ir(repaired, tuple(tool_runs))
            compiled = compile_animation_ir(repaired, tuple(tool_runs))
        except (IrValidationError, UnsupportedFeature) as error:
            events.append(AgentEvent(stage="ir_repair", status="failed", message=str(error)))
        else:
            ir = repaired
            source = _compiled_program_source(compiled)
            critic = evaluate_expression(ir, tuple(tool_runs), source, provider=critic_provider)
            repair_count = 1
            events.append(AgentEvent(stage="ir_repair", status="succeeded", message="ir_repair"))
    return AgentExecution(
        response=AgentRunResponse(
            outcome=AgentRunOutcome.READY,
            intent=intent,
            tool_runs=tuple(tool_runs),
            animation_ir=ir,
            events=tuple(events),
            critic_report=critic,
            repair_count=repair_count,
        ),
        compiled_program=compiled,
    )


def _compiled_program_source(program: CompiledProgram) -> str:
    """Provide the critic every ordered segment without treating one as canonical."""
    return "\n\n".join(segment.source for segment in program.segments)


def describe_intent(intent: IntentSpec) -> str:
    return f"{intent.domain.value}: {intent.goal}"
