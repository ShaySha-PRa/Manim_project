"""Core IR types shared by renderer backends."""

from __future__ import annotations

from dataclasses import dataclass

from manim_workbench_contracts.ir import VisualKind


class UnsupportedFeature(ValueError):
    """Capability cannot be lowered by this renderer backend."""


@dataclass(frozen=True, slots=True)
class CompiledSegment:
    source: str
    scene_base: str
    visual_kinds: tuple[VisualKind, ...]
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class CompiledProgram:
    segments: tuple[CompiledSegment, ...]

    @property
    def requires_concat(self) -> bool:
        return len(self.segments) > 1
