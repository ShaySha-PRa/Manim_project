from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from manim_workbench_contracts import (
    AgentRunOutcome,
    Audience,
    CodeGenerationCategory,
    CodeGenerationRequest,
    ContentPlanGenerationRequest,
    ContentPlanOutcome,
    GlobalBrief,
    SceneBlockVersion,
    ScenePipeline,
)

from manim_workbench_api.agent.orchestrator import run_agent_with_program
from manim_workbench_api.code_generation.service import CodeGenerationService
from manim_workbench_api.compiler.base import CompiledProgram
from manim_workbench_api.content_plans.service import ContentPlanService
from manim_workbench_api.projects.repository import ProjectRepository

_FUNCTION = re.compile(r"函数|图像|曲线|坐标|function|graph|plot|curve|axis", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SceneAdapterStopped(Exception):
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class SceneCompilation:
    pipeline: ScenePipeline
    program: CompiledProgram
    prompt_version_id: UUID
    content_plan_version_id: UUID | None
    intent: Any | None = None
    tool_runs: tuple[Any, ...] = ()
    animation_ir: Any | None = None
    provenance: tuple[tuple[str, str], ...] = ()


class TeachingSceneAdapter:
    def __init__(
        self,
        projects: ProjectRepository,
        content_plans: ContentPlanService,
        code_generation: CodeGenerationService,
    ) -> None:
        self._projects = projects
        self._content_plans = content_plans
        self._code_generation = code_generation

    def compile(
        self,
        block: SceneBlockVersion,
        global_brief: GlobalBrief,
        *,
        previous_scene_summary: str | None = None,
    ) -> SceneCompilation:
        project = self._projects.get_project(block.project_id, block.owner_id)
        if project.archived_at is not None:
            raise SceneAdapterStopped("project_not_found", "Project was not found.")
        prompt = self._projects.append_prompt_version(
            block.project_id, block.owner_id, block.prompt
        )
        plan_request = ContentPlanGenerationRequest(
            project_id=block.project_id,
            owner_id=block.owner_id,
            prompt_version_id=prompt.id,
            audience=Audience.UNDERGRADUATE,
            language=global_brief.language,
            target_duration_seconds=block.target_duration_seconds,
            explicit_assumptions=_brief_assumptions(
                global_brief, previous_scene_summary
            ),
        )
        generated = self._content_plans.generate(plan_request)
        if (
            generated.outcome is not ContentPlanOutcome.READY
            or generated.content_plan_version is None
        ):
            code = (
                "needs_confirmation"
                if generated.outcome is ContentPlanOutcome.NEEDS_CLARIFICATION
                else "teaching_scope_unsupported"
            )
            raise SceneAdapterStopped(code, "Teaching plan is not ready to compile.")
        category = (
            CodeGenerationCategory.FUNCTION_VISUALIZATION
            if _FUNCTION.search(block.prompt)
            else CodeGenerationCategory.FORMULA_DERIVATION
        )
        code_request = CodeGenerationRequest(
            project_id=block.project_id,
            owner_id=block.owner_id,
            prompt_version_id=prompt.id,
            content_plan_version_id=generated.content_plan_version.id,
            category=category,
        )
        program = self._code_generation.compile_program(code_request)
        return SceneCompilation(
            pipeline=ScenePipeline.TEACHING,
            program=program,
            prompt_version_id=prompt.id,
            content_plan_version_id=generated.content_plan_version.id,
            provenance=(
                ("pipeline", "teaching"),
                ("prompt_version_id", str(prompt.id)),
                ("content_plan_version_id", str(generated.content_plan_version.id)),
                ("global_brief_title", global_brief.title),
                ("global_brief_sha256", _brief_sha256(global_brief)),
                ("previous_scene_summary", previous_scene_summary or ""),
            ),
        )


class ScientificSceneAdapter:
    def __init__(
        self,
        projects: ProjectRepository,
        *,
        compute_root: Path,
        provider: Any | None = None,
    ) -> None:
        self._projects = projects
        self._compute_root = compute_root
        self._provider = provider

    def compile(
        self,
        block: SceneBlockVersion,
        global_brief: GlobalBrief,
        *,
        csv_text: str | None = None,
        paper_text: str | None = None,
        previous_scene_summary: str | None = None,
    ) -> SceneCompilation:
        project = self._projects.get_project(block.project_id, block.owner_id)
        if project.archived_at is not None:
            raise SceneAdapterStopped("project_not_found", "Project was not found.")
        prompt = self._projects.append_prompt_version(
            block.project_id, block.owner_id, block.prompt
        )
        execution = run_agent_with_program(
            block.prompt,
            target_duration_seconds=block.target_duration_seconds,
            csv_text=csv_text,
            paper_text=paper_text,
            output_root=self._compute_root,
            provider=self._provider,
            engine=self._projects._engine,
            owner_id=block.owner_id,
            project_id=block.project_id,
            intent_assumptions=_brief_assumptions(
                global_brief, previous_scene_summary
            ),
        )
        response = execution.response
        if response.outcome is not AgentRunOutcome.READY or execution.compiled_program is None:
            raise SceneAdapterStopped(
                response.error_code or response.outcome.value,
                response.message or "Scientific scene is not ready to compile.",
            )
        return SceneCompilation(
            pipeline=ScenePipeline.SCIENTIFIC,
            program=execution.compiled_program,
            prompt_version_id=prompt.id,
            content_plan_version_id=None,
            intent=response.intent,
            tool_runs=tuple(response.tool_runs),
            animation_ir=response.animation_ir,
            provenance=(
                ("pipeline", "scientific"),
                ("prompt_version_id", str(prompt.id)),
                ("global_brief_title", global_brief.title),
                ("global_brief_sha256", _brief_sha256(global_brief)),
                ("asset_hashes", ",".join(run.output_sha256 for run in response.tool_runs)),
                ("previous_scene_summary", previous_scene_summary or ""),
            ),
        )


def _brief_assumptions(
    brief: GlobalBrief, previous_scene_summary: str | None
) -> tuple[str, ...]:
    assumptions = [
        f"Use the shared {brief.style_preset.value} workflow style.",
        f"Use background {brief.background}.",
        f"Use palette {', '.join(brief.palette)}.",
        f"Use language {brief.language.value}.",
    ]
    if brief.notation:
        assumptions.append(
            "Notation: " + ", ".join(f"{key}={value}" for key, value in brief.notation.items())
        )
    if brief.scientific_parameters:
        assumptions.append(
            "Scientific parameters: "
            + ", ".join(
                f"{key}={value:g}" for key, value in brief.scientific_parameters.items()
            )
        )
    if previous_scene_summary:
        assumptions.append(f"Previous scene context: {previous_scene_summary[:120]}")
    return tuple(assumptions)


def _brief_sha256(brief: GlobalBrief) -> str:
    canonical = json.dumps(
        brief.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
