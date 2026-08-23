"""Persist an Animation Agent run onto the existing version chain."""

from __future__ import annotations

import os
from pathlib import Path

from manim_workbench_contracts import (
    AgentRunRequest,
    AgentRunResponse,
    CodeGenerationMode,
    CodeGenerationRequest,
    CodeModelResponse,
    ContentPlanDraft,
    ContentPlanGenerationRequest,
    ContentPlanScene,
    DerivationStyle,
    FormulaStep,
    VisualKind,
)
from manim_workbench_contracts.intent import AgentRunOutcome

from manim_workbench_api.agent.orchestrator import run_agent
from manim_workbench_api.code_generation.repository import CodeGenerationRepository
from manim_workbench_api.code_generation.security import validate_source_security
from manim_workbench_api.compiler.manim import compile_animation_ir
from manim_workbench_api.content_plans.errors import ContentPlanError
from manim_workbench_api.content_plans.models import ProviderResult
from manim_workbench_api.content_plans.provider import DeepSeekProvider
from manim_workbench_api.content_plans.repository import ContentPlanRepository
from manim_workbench_api.projects.repository import ProjectRepository


class AgentService:
    def __init__(
        self,
        projects: ProjectRepository,
        content_plans: ContentPlanRepository,
        code_versions: CodeGenerationRepository,
        *,
        compute_root: Path | None = None,
    ) -> None:
        self._projects = projects
        self._content_plans = content_plans
        self._code_versions = code_versions
        self._compute_root = compute_root or Path(
            os.environ.get("MANIM_WORKBENCH_COMPUTE_ROOT", "runtime/compute-artifacts")
        )

    def run(self, request: AgentRunRequest) -> AgentRunResponse:
        self._projects.get_project(request.project_id, request.owner_id)
        generated = run_agent(
            request.prompt,
            target_duration_seconds=request.target_duration_seconds,
            csv_text=request.csv_text,
            paper_text=request.paper_text,
            output_root=self._compute_root,
            provider=_intent_provider(),
            engine=self._projects._engine,
            owner_id=request.owner_id,
            project_id=request.project_id,
        )
        prompt = self._projects.append_prompt_version(
            request.project_id,
            request.owner_id,
            request.prompt,
        )
        if generated.outcome is not AgentRunOutcome.READY or generated.intent is None:
            return generated.model_copy(update={"prompt_version": prompt})
        if generated.animation_ir is None:
            return generated.model_copy(update={"prompt_version": prompt})
        draft = ContentPlanDraft(
            schema_version="1.1",
            title=generated.intent.goal[:200],
            audience=request.audience,
            language=request.language,
            target_duration_seconds=request.target_duration_seconds,
            derivation_style=DerivationStyle.VISUAL_INTUITION,
            explicit_assumptions=generated.intent.assumptions,
            ambiguities=(),
            scenes=(
                ContentPlanScene(
                    scene_number=1,
                    teaching_goal=generated.intent.goal[:1000],
                    formula_steps=(
                        FormulaStep(
                            expression=generated.intent.domain.value,
                            explanation="Animation Agent V2: tools then AnimationIR",
                        ),
                    ),
                    visual_intent=generated.animation_ir.pattern.value,
                    narration_placeholder=generated.intent.goal[:4000],
                    visual_kind=(
                        VisualKind.THREE_D
                        if generated.intent.dimension == "3d"
                        else VisualKind.FUNCTION
                    ),
                ),
            ),
        )
        plan = self._content_plans.save_ready(
            ContentPlanGenerationRequest(
                project_id=request.project_id,
                owner_id=request.owner_id,
                prompt_version_id=prompt.id,
                audience=request.audience,
                language=request.language,
                target_duration_seconds=request.target_duration_seconds,
            ),
            draft,
            attempt_number=1,
            provider_result=ProviderResult(
                content=generated.animation_ir.model_dump_json(),
                model="animation-agent-v2",
            ),
        )
        compiled = compile_animation_ir(generated.animation_ir, generated.tool_runs)
        source = compiled.segments[0].source
        report = validate_source_security(source)
        if not report.allowed:
            codes = ",".join(item.code for item in report.findings[:8])
            return generated.model_copy(
                update={
                    "outcome": AgentRunOutcome.FAILED,
                    "error_code": "security_policy_violation",
                    "message": codes,
                    "prompt_version": prompt,
                    "content_plan_version": plan,
                }
            )
        code = self._code_versions.save_success(
            CodeGenerationRequest(
                project_id=request.project_id,
                owner_id=request.owner_id,
                prompt_version_id=prompt.id,
                content_plan_version_id=plan.id,
                category=generated.intent.category_hint,
            ),
            response=CodeModelResponse(
                scene_class="GeneratedScene",
                code=source,
                assumptions=generated.intent.assumptions,
            ),
            attempt_number=1,
            mode=CodeGenerationMode.COMPILED_IR,
            prompt_template_version="animation-agent-v2",
            provider_model="compiler+tools",
        )
        return generated.model_copy(
            update={
                "prompt_version": prompt,
                "content_plan_version": plan,
                "code_version": code,
            }
        )


def _intent_provider() -> DeepSeekProvider | None:
    try:
        return DeepSeekProvider()
    except ContentPlanError:
        return None
