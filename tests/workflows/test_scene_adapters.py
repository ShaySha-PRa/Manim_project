from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from manim_workbench_api.code_generation.models import CandidateRenderResult
from manim_workbench_api.code_generation.repository import CodeGenerationRepository
from manim_workbench_api.code_generation.service import CodeGenerationService
from manim_workbench_api.content_plans.models import ProviderResult
from manim_workbench_api.content_plans.repository import ContentPlanRepository
from manim_workbench_api.content_plans.service import ContentPlanService
from manim_workbench_api.database import create_database_engine
from manim_workbench_api.projects.repository import ProjectRepository
from manim_workbench_api.workflows import ScientificSceneAdapter, TeachingSceneAdapter
from manim_workbench_contracts import (
    GlobalBrief,
    Language,
    SceneBlockVersion,
    ScenePipeline,
    ScenePipelineMode,
    WorkflowStylePreset,
)
from sqlalchemy import Engine, text

from tests.workflows.migration_support import upgrade_workflow_database

OWNER = UUID("00000000-0000-0000-0000-000000000001")
PROJECT = UUID("10000000-0000-0000-0000-000000000001")
WORKFLOW = UUID("20000000-0000-0000-0000-000000000001")


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    path = tmp_path / "adapters.db"
    upgrade_workflow_database(path)
    result = create_database_engine(f"sqlite:///{path}")
    now = "2026-08-23T00:00:00+00:00"
    with result.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id,email,created_at) VALUES (:id,'owner@test.dev',:now)"),
            {"id": str(OWNER), "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO projects (id,owner_id,title,created_at) "
                "VALUES (:id,:owner,'Adapters',:now)"
            ),
            {"id": str(PROJECT), "owner": str(OWNER), "now": now},
        )
    return result


def _brief() -> GlobalBrief:
    return GlobalBrief(
        title="Unified scientific lesson",
        language=Language.ZH_CN,
        target_duration_seconds=120,
        style_preset=WorkflowStylePreset.DARK_SCIENTIFIC,
        background="#101018",
        palette=("#4488ff", "#ffcc22", "#ff4444"),
        notation={"x": "state"},
        scientific_parameters={"rho": 28.0},
    )


def _block(
    prompt: str,
    mode: ScenePipelineMode,
    *,
    target_duration_seconds: int = 60,
) -> SceneBlockVersion:
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
        target_duration_seconds=target_duration_seconds,
        created_at=datetime.now(timezone.utc),
    )


class TeachingPlanProvider:
    def __init__(self, target_duration_seconds: int = 60) -> None:
        self.target_duration_seconds = target_duration_seconds

    def generate(self, _messages):  # type: ignore[no-untyped-def]
        assumptions = [
            "Use the shared dark_scientific workflow style.",
            "Use background #101018.",
            "Use palette #4488ff, #ffcc22, #ff4444.",
            "Use language zh-CN.",
            "Notation: x=state",
            "Scientific parameters: rho=28",
        ]
        return ProviderResult(
            model="test-teaching-planner",
            content=json.dumps(
                {
                    "outcome": "ready",
                    "plan": {
                        "schema_version": "1.1",
                        "title": "勾股定理",
                        "audience": "undergraduate",
                        "language": "zh-CN",
                        "target_duration_seconds": self.target_duration_seconds,
                        "derivation_style": "conceptual",
                        "explicit_assumptions": assumptions,
                        "ambiguities": [],
                        "scenes": [
                            {
                                "scene_number": 1,
                                "teaching_goal": "解释直角三角形三边关系。",
                                "formula_steps": [
                                    {
                                        "expression": "a^2+b^2=c^2",
                                        "explanation": "两直角边平方和等于斜边平方。",
                                    }
                                ],
                                "visual_intent": "逐步显示公式与三角形含义。",
                                "narration_placeholder": "说明勾股定理。",
                            }
                        ],
                    },
                    "clarifications": [],
                    "limitations": [],
                },
                ensure_ascii=False,
            ),
        )


class UnusedCodeProvider:
    def generate(self, _messages):  # type: ignore[no-untyped-def]
        raise AssertionError("deterministic teaching compilation must not call code provider")


class UnusedRenderer:
    def render(self, _source: str, _scene_class: str) -> CandidateRenderResult:
        raise AssertionError("compile_program must not render synchronously")


def test_teaching_adapter_persists_prompt_plan_and_compiles_complete_program(
    engine: Engine,
) -> None:
    projects = ProjectRepository(engine)
    adapter = TeachingSceneAdapter(
        projects,
        ContentPlanService(ContentPlanRepository(engine), TeachingPlanProvider(15)),
        CodeGenerationService(
            CodeGenerationRepository(engine), UnusedCodeProvider(), UnusedRenderer()
        ),
    )
    result = adapter.compile(
        _block(
            "解释勾股定理的公式含义。",
            ScenePipelineMode.TEACHING,
            target_duration_seconds=15,
        ),
        _brief(),
    )
    assert result.pipeline is ScenePipeline.TEACHING
    assert len(result.program.segments) == 1
    assert result.program.segments[0].duration_seconds == 15
    assert "a^2+b^2=c^2" in result.program.segments[0].source
    assert result.content_plan_version_id is not None
    provenance = dict(result.provenance)
    assert len(provenance["global_brief_sha256"]) == 64
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM prompt_versions")).scalar_one() == 1
        assert connection.execute(
            text("SELECT COUNT(*) FROM content_plan_versions")
        ).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM code_versions")).scalar_one() == 0


def test_scientific_adapter_runs_catalog_tools_ir_and_deterministic_compiler(
    engine: Engine, tmp_path: Path
) -> None:
    adapter = ScientificSceneAdapter(
        ProjectRepository(engine), compute_root=tmp_path / "scientific"
    )
    result = adapter.compile(
        _block(
            "展示三个初值只差 1e-5 的 Lorenz 系统轨迹逐渐分离。",
            ScenePipelineMode.SCIENTIFIC,
        ),
        _brief(),
    )
    assert result.pipeline is ScenePipeline.SCIENTIFIC
    assert result.intent is not None
    assert result.animation_ir is not None
    assert result.tool_runs
    assert result.program.segments
    assert "paths_arr" in result.program.segments[0].source
    assert "Use background #101018." in result.intent.assumptions
    assert "Scientific parameters: rho=28" in result.intent.assumptions
    provenance = dict(result.provenance)
    assert provenance["asset_hashes"] == result.tool_runs[0].output_sha256
    assert len(provenance["global_brief_sha256"]) == 64
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM prompt_versions")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM asset_versions")).scalar_one() >= 1
