from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from manim_workbench_contracts import (
    GlobalBrief,
    SceneBlockRunStatus,
    SceneBlockVersion,
    ScenePipeline,
    ScenePipelineMode,
)

from manim_workbench_api.program_rendering import ProgramQualityPolicy

from .adapters import SceneAdapterStopped, SceneCompilation

_SCIENTIFIC = re.compile(
    r"csv|论文|paper|模拟|simulation|ode|微分方程|轨迹|trajectory|数值|numeric|"
    r"数据|dataset|lorenz|洛伦兹|fourier|傅里叶|波动|wave",
    re.IGNORECASE,
)
_TEACHING = re.compile(
    r"公式.*(?:推导|讲解)|推导.*公式|几何.*(?:证明|讲解)|证明.*几何|教学讲解|"
    r"explain|teach|deriv|formula|geometry proof",
    re.IGNORECASE,
)
_CSV = re.compile(r"csv|表格数据|实验数据|dataset", re.IGNORECASE)
_PAPER = re.compile(r"论文|paper|pdf|文献", re.IGNORECASE)


class TeachingAdapter(Protocol):
    def compile(
        self,
        block: SceneBlockVersion,
        global_brief: GlobalBrief,
        *,
        previous_scene_summary: str | None = None,
    ) -> SceneCompilation: ...


class ScientificAdapter(Protocol):
    def compile(
        self,
        block: SceneBlockVersion,
        global_brief: GlobalBrief,
        *,
        csv_text: str | None = None,
        paper_text: str | None = None,
        previous_scene_summary: str | None = None,
    ) -> SceneCompilation: ...


@dataclass(frozen=True, slots=True)
class ScenePreparation:
    status: SceneBlockRunStatus
    pipeline: ScenePipeline | None = None
    compilation: SceneCompilation | None = None
    error_code: str | None = None


def route_scene_pipeline(prompt: str) -> ScenePipeline | None:
    scientific = bool(_SCIENTIFIC.search(prompt))
    teaching = bool(_TEACHING.search(prompt))
    if scientific == teaching:
        return None
    return ScenePipeline.SCIENTIFIC if scientific else ScenePipeline.TEACHING


def quality_policy_for_pipeline(pipeline: ScenePipeline) -> ProgramQualityPolicy:
    if pipeline is ScenePipeline.TEACHING:
        return ProgramQualityPolicy.TEACHING
    return ProgramQualityPolicy.SCIENTIFIC


class SceneBlockExecutor:
    def __init__(self, teaching: TeachingAdapter, scientific: ScientificAdapter) -> None:
        self._teaching = teaching
        self._scientific = scientific

    def prepare(
        self,
        block: SceneBlockVersion,
        global_brief: GlobalBrief,
        *,
        csv_text: str | None = None,
        paper_text: str | None = None,
        previous_scene_summary: str | None = None,
    ) -> ScenePreparation:
        pipeline = self._select_pipeline(block)
        if pipeline is None:
            return ScenePreparation(
                status=SceneBlockRunStatus.NEEDS_CONFIRMATION,
                error_code="pipeline_confirmation_required",
            )
        if pipeline is ScenePipeline.SCIENTIFIC:
            if _CSV.search(block.prompt) and not csv_text:
                return ScenePreparation(
                    status=SceneBlockRunStatus.ASSET_REQUIRED,
                    pipeline=pipeline,
                    error_code="csv_asset_required",
                )
            if _PAPER.search(block.prompt) and not paper_text:
                return ScenePreparation(
                    status=SceneBlockRunStatus.NEEDS_CONFIRMATION,
                    pipeline=pipeline,
                    error_code="paper_content_required",
                )
        try:
            if pipeline is ScenePipeline.TEACHING:
                compiled = self._teaching.compile(
                    block,
                    global_brief,
                    previous_scene_summary=previous_scene_summary,
                )
            else:
                compiled = self._scientific.compile(
                    block,
                    global_brief,
                    csv_text=csv_text,
                    paper_text=paper_text,
                    previous_scene_summary=previous_scene_summary,
                )
        except SceneAdapterStopped as stopped:
            if stopped.code == "asset_required" or stopped.code.endswith("_asset_required"):
                status = SceneBlockRunStatus.ASSET_REQUIRED
            elif "confirmation" in stopped.code:
                status = SceneBlockRunStatus.NEEDS_CONFIRMATION
            else:
                status = SceneBlockRunStatus.FAILED
            return ScenePreparation(status=status, pipeline=pipeline, error_code=stopped.code)
        return ScenePreparation(
            status=SceneBlockRunStatus.COMPILING,
            pipeline=pipeline,
            compilation=compiled,
        )

    @staticmethod
    def _select_pipeline(block: SceneBlockVersion) -> ScenePipeline | None:
        if block.pipeline_mode is ScenePipelineMode.TEACHING:
            return ScenePipeline.TEACHING
        if block.pipeline_mode is ScenePipelineMode.SCIENTIFIC:
            return ScenePipeline.SCIENTIFIC
        return route_scene_pipeline(block.prompt)
