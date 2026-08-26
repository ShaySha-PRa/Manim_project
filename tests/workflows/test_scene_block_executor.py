from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from manim_workbench_api.compiler.base import CompiledProgram, CompiledSegment
from manim_workbench_api.program_rendering import ProgramQualityPolicy
from manim_workbench_api.workflows import (
    SceneBlockExecutor,
    SceneCompilation,
    quality_policy_for_pipeline,
    route_scene_pipeline,
)
from manim_workbench_contracts import (
    GlobalBrief,
    Language,
    SceneBlockRunStatus,
    SceneBlockVersion,
    ScenePipeline,
    ScenePipelineMode,
    WorkflowStylePreset,
)

OWNER = UUID("00000000-0000-0000-0000-000000000001")
PROJECT = UUID("10000000-0000-0000-0000-000000000001")
WORKFLOW = UUID("20000000-0000-0000-0000-000000000001")


def _brief() -> GlobalBrief:
    return GlobalBrief(
        title="Workflow",
        language=Language.ZH_CN,
        target_duration_seconds=120,
        style_preset=WorkflowStylePreset.MINIMAL_MATH,
        background="#111111",
        palette=("#ffffff",),
    )


def _block(prompt: str, mode: ScenePipelineMode = ScenePipelineMode.AUTO) -> SceneBlockVersion:
    return SceneBlockVersion(
        id=uuid4(),
        workflow_id=WORKFLOW,
        project_id=PROJECT,
        owner_id=OWNER,
        version=1,
        parent_version_id=None,
        title="Scene",
        prompt=prompt,
        pipeline_mode=mode,
        target_duration_seconds=30,
        created_at=datetime.now(timezone.utc),
    )


class RecordingAdapter:
    def __init__(self, pipeline: ScenePipeline) -> None:
        self.pipeline = pipeline
        self.calls = 0

    def compile(self, block, _brief, **_kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        return SceneCompilation(
            pipeline=self.pipeline,
            program=CompiledProgram(
                segments=(
                    CompiledSegment(
                        source="class GeneratedScene: pass",
                        scene_base="Scene",
                        visual_kinds=(),
                        duration_seconds=30,
                    ),
                )
            ),
            prompt_version_id=block.id,
            content_plan_version_id=None,
        )


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("根据 CSV 实验数据展示温度变化。", ScenePipeline.SCIENTIFIC),
        ("模拟 Lorenz 轨迹的数值变化。", ScenePipeline.SCIENTIFIC),
        ("教学讲解这个公式的推导。", ScenePipeline.TEACHING),
        ("给出几何证明并解释每一步。", ScenePipeline.TEACHING),
        ("做一个漂亮的动画。", None),
        ("教学讲解这篇论文的数据。", None),
    ],
)
def test_closed_auto_router(prompt: str, expected: ScenePipeline | None) -> None:
    assert route_scene_pipeline(prompt) is expected


def test_auto_unknown_csv_missing_and_unknown_paper_stop_before_adapters() -> None:
    teaching = RecordingAdapter(ScenePipeline.TEACHING)
    scientific = RecordingAdapter(ScenePipeline.SCIENTIFIC)
    executor = SceneBlockExecutor(teaching, scientific)

    ambiguous = executor.prepare(_block("做一个漂亮的动画。"), _brief())
    missing_csv = executor.prepare(_block("根据 CSV 展示实验数据。"), _brief())
    missing_paper = executor.prepare(_block("复现这篇论文中的结果。"), _brief())

    assert ambiguous.status is SceneBlockRunStatus.NEEDS_CONFIRMATION
    assert ambiguous.error_code == "pipeline_confirmation_required"
    assert missing_csv.status is SceneBlockRunStatus.ASSET_REQUIRED
    assert missing_csv.error_code == "csv_asset_required"
    assert missing_paper.status is SceneBlockRunStatus.NEEDS_CONFIRMATION
    assert missing_paper.error_code == "paper_content_required"
    assert teaching.calls == scientific.calls == 0


def test_manual_modes_and_ready_auto_only_call_selected_adapter() -> None:
    teaching = RecordingAdapter(ScenePipeline.TEACHING)
    scientific = RecordingAdapter(ScenePipeline.SCIENTIFIC)
    executor = SceneBlockExecutor(teaching, scientific)

    taught = executor.prepare(
        _block("ambiguous request", ScenePipelineMode.TEACHING), _brief()
    )
    researched = executor.prepare(
        _block("展示 Lorenz 轨迹。"), _brief(), previous_scene_summary="equations"
    )

    assert taught.status is SceneBlockRunStatus.COMPILING
    assert taught.pipeline is ScenePipeline.TEACHING
    assert researched.status is SceneBlockRunStatus.COMPILING
    assert researched.pipeline is ScenePipeline.SCIENTIFIC
    assert teaching.calls == scientific.calls == 1


def test_pipeline_selects_its_own_quality_policy() -> None:
    assert quality_policy_for_pipeline(ScenePipeline.TEACHING) is ProgramQualityPolicy.TEACHING
    assert (
        quality_policy_for_pipeline(ScenePipeline.SCIENTIFIC)
        is ProgramQualityPolicy.SCIENTIFIC
    )
