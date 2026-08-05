from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from manim_workbench_contracts import ContentPlanVersion

from manim_workbench_api.content_plans.models import ProviderMessage, ProviderResult


class CodeGenerationProvider(Protocol):
    def generate(self, messages: tuple[ProviderMessage, ...]) -> ProviderResult: ...


@dataclass(frozen=True, slots=True)
class CandidateRenderResult:
    succeeded: bool
    error_code: str | None = None
    diagnostic: str = ""


class CandidateRenderer(Protocol):
    def render(
        self, source_code: str, scene_class: Literal["GeneratedScene"]
    ) -> CandidateRenderResult: ...


@dataclass(frozen=True, slots=True)
class LoadedCodeGenerationInput:
    content_plan: ContentPlanVersion
