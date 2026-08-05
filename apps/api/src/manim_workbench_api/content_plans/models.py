from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, Protocol

from manim_workbench_contracts import ContentPlanGenerationResponse
from pydantic import BaseModel, ConfigDict, Field


class ProviderMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["system", "user"]
    content: Annotated[str, Field(min_length=1, max_length=40_000)]


class ProviderUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_tokens: Annotated[int, Field(ge=0)] = 0
    completion_tokens: Annotated[int, Field(ge=0)] = 0


class ProviderResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: Annotated[str, Field(max_length=200_000)]
    finish_reason: Annotated[str | None, Field(max_length=100)] = None
    request_id: Annotated[str | None, Field(max_length=200)] = None
    model: Annotated[str, Field(min_length=1, max_length=100)]
    usage: ProviderUsage = ProviderUsage()


class ContentPlanProvider(Protocol):
    def generate(self, messages: tuple[ProviderMessage, ...]) -> ProviderResult: ...


@dataclass(frozen=True)
class PromptRecord:
    prompt_version_id: str
    prompt: str


__all__ = [
    "ContentPlanGenerationResponse",
    "ContentPlanProvider",
    "PromptRecord",
    "ProviderMessage",
    "ProviderResult",
    "ProviderUsage",
]
