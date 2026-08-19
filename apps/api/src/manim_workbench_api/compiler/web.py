"""Web preview backend: walks AnimationIR into JSON. Never emits Manim Python."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from manim_workbench_contracts import ToolRun
from manim_workbench_contracts.animation_ir import (
    AnimationIR,
    AnimBinding,
    AnimCameraOp,
    AnimObject,
    DataRef,
    StateSpec,
    TimelineOp,
)

from manim_workbench_api.compiler.base import UnsupportedFeature


class WebBackend:
    def select_scene_base(self, ir: AnimationIR) -> str:
        return "Web3DScene" if ir.scene.dimension == "3d" else "WebScene"

    def begin(
        self,
        ir: AnimationIR,
        scene_base: str,
        tool_runs: tuple[ToolRun, ...],
    ) -> WebEmitContext:
        return WebEmitContext(ir=ir, scene_base=scene_base, tool_runs=tool_runs)


@dataclass
class WebEmitContext:
    ir: AnimationIR
    scene_base: str
    tool_runs: tuple[ToolRun, ...]
    duration_seconds: float = 0.0
    _data: list[dict[str, object]] = field(default_factory=list)
    _states: list[dict[str, object]] = field(default_factory=list)
    _objects: list[dict[str, object]] = field(default_factory=list)
    _bindings: list[dict[str, object]] = field(default_factory=list)
    _timeline: list[dict[str, object]] = field(default_factory=list)
    _camera: list[dict[str, object]] = field(default_factory=list)

    def register_data(self, spec: DataRef) -> None:
        run = next(
            (item for item in self.tool_runs if item.artifact_ref == spec.artifact_ref),
            None,
        )
        keys: list[str] = []
        if run is not None:
            packed = np.load(Path(run.artifact_path), allow_pickle=False)
            keys = [name for name in packed.files if name != "assertion_json"]
        self._data.append(
            {
                "id": spec.id,
                "kind": spec.kind.value,
                "artifact_ref": spec.artifact_ref,
                "output_sha256": spec.output_sha256,
                "arrays": keys,
            }
        )

    def emit_state(self, spec: StateSpec) -> None:
        self._states.append({"id": spec.id, "type": spec.type.value, "initial": spec.initial})

    def emit_object(self, obj: AnimObject) -> None:
        self._objects.append(
            {
                "id": obj.id,
                "type": obj.type.value,
                "data_ref": obj.data_ref,
                "text": obj.text,
                "color": obj.color,
            }
        )

    def emit_binding(self, binding: AnimBinding) -> None:
        self._bindings.append(
            {
                "target": binding.target,
                "op": binding.source.op.value,
                "data": binding.source.data,
                "state": binding.source.state,
            }
        )

    def emit_timeline(self, ops: tuple[TimelineOp, ...]) -> None:
        for op in ops:
            self._timeline.append(
                {
                    "op": op.op.value,
                    "target": op.target,
                    "targets": list(op.targets),
                    "duration": op.duration,
                }
            )
            self.duration_seconds += op.duration

    def emit_camera(self, ops: tuple[AnimCameraOp, ...]) -> None:
        for op in ops:
            self._camera.append({"op": op.op.value, "target": op.target, "rate": op.rate})

    def finish(self) -> str:
        payload = {
            "backend": "web",
            "scene_base": self.scene_base,
            "domain": self.ir.domain,
            "goal": self.ir.goal,
            "dimension": self.ir.scene.dimension,
            "data": self._data,
            "states": self._states,
            "objects": self._objects,
            "bindings": self._bindings,
            "timeline": self._timeline,
            "camera": self._camera,
            "assertions": [item.type.value for item in self.ir.assertions],
        }
        source = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if "lambda" in source or "from manim" in source.lower():
            raise UnsupportedFeature("web backend emitted Python")
        return source
