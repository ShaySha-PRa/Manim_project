from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine

from manim_workbench_api.content_plans.provider import DeepSeekProvider
from manim_workbench_api.database import create_database_engine
from manim_workbench_api.phase7_runtime import Phase7SandboxRenderer

from .models import CandidateRenderer, CodeGenerationProvider


def get_code_generation_engine() -> Engine:
    return create_database_engine()


def get_code_generation_provider() -> CodeGenerationProvider:
    return DeepSeekProvider()


def get_code_generation_renderer() -> CandidateRenderer:
    project_root = Path(__file__).resolve().parents[5]
    return Phase7SandboxRenderer(runtime_root=project_root / "runtime" / "phase7-candidates")
