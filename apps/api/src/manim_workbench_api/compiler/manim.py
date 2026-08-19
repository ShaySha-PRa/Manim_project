"""Deterministic Manim lowering for AnimationIR 2.0.

Walks data / states / objects / bindings / timeline / camera. Never
dispatches on the IR pattern field. Never emits lambda.
"""

# Generated Scene source is stored as string literals; keep those lines intact.
# ruff: noqa: E501

from __future__ import annotations

import hashlib
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
    AssertionType,
    BindingOp,
    CameraOpKind,
    DataRef,
    FallbackStrategy,
    ObjectType,
    StateSpec,
    StateType,
    TimelineOp,
    TimelineOpKind,
)
from manim_workbench_contracts.ir import VisualKind

from manim_workbench_api.agent.ir_validator import validate_animation_ir
from manim_workbench_api.compiler.base import CompiledProgram, CompiledSegment, UnsupportedFeature
from manim_workbench_api.compiler.web import WebBackend

_TITLE_FONT = "Noto Sans CJK SC"
_MOVING_CAMERA_OPS = frozenset({CameraOpKind.ZOOM, CameraOpKind.FOLLOW})
_IMPORT_ORDER = (
    "Scene",
    "MovingCameraScene",
    "ThreeDScene",
    "Text",
    "ImageMobject",
    "Axes",
    "ThreeDAxes",
    "Line",
    "DashedLine",
    "VGroup",
    "Dot",
    "Arrow",
    "Rectangle",
    "FadeIn",
    "ValueTracker",
    "always_redraw",
    "UP",
    "DOWN",
    "YELLOW",
    "BLUE",
    "GRAY",
    "GREEN",
    "ORANGE",
    "RED",
    "WHITE",
    "linear",
)


def _text_literal(value: str) -> str:
    return repr(value)


@dataclass
class RegisteredData:
    spec: DataRef
    packed_var: str
    asset: str
    keys: frozenset[str]
    shapes: dict[str, tuple[int, ...]]


class ManimBackend:
    def select_scene_base(self, ir: AnimationIR) -> str:
        if ir.scene.dimension == "3d":
            return "ThreeDScene"
        if any(op.op in _MOVING_CAMERA_OPS for op in ir.camera):
            if _fallback_fixed_camera(ir):
                return "Scene"
            return "MovingCameraScene"
        return "Scene"

    def begin(
        self,
        ir: AnimationIR,
        scene_base: str,
        tool_runs: tuple[ToolRun, ...],
    ) -> ManimEmitContext:
        return ManimEmitContext(ir=ir, scene_base=scene_base, tool_runs=tool_runs)


class RendererRegistry:
    def require(self, renderer_hint: str) -> ManimBackend | WebBackend:
        if renderer_hint == "manim":
            return ManimBackend()
        if renderer_hint == "web":
            return WebBackend()
        raise UnsupportedFeature(f"unknown renderer backend: {renderer_hint}")


renderer_registry = RendererRegistry()


def _fallback_fixed_camera(ir: AnimationIR) -> bool:
    return any(item.strategy is FallbackStrategy.FIXED_CAMERA for item in ir.fallbacks) and not any(
        op.op in _MOVING_CAMERA_OPS or op.op is CameraOpKind.AMBIENT_ROTATE for op in ir.camera
    )


def compile_animation_ir(
    ir: AnimationIR,
    tool_runs: tuple[ToolRun, ...],
    *,
    backend: str | None = None,
    cache_root: Path | None = None,
) -> CompiledProgram:
    hint = backend or ir.scene.renderer_hint
    if backend and backend != ir.scene.renderer_hint:
        ir = ir.model_copy(
            update={"scene": ir.scene.model_copy(update={"renderer_hint": backend})}
        )
    cache_key = _compile_cache_key(ir, tool_runs, hint)
    if cache_root is not None:
        cached = _read_compile_cache(cache_root, cache_key)
        if cached is not None:
            return cached
    program = _compile_animation_ir(ir, tool_runs, hint)
    if cache_root is not None:
        _write_compile_cache(cache_root, cache_key, program)
    return program


def _compile_cache_key(ir: AnimationIR, tool_runs: tuple[ToolRun, ...], hint: str) -> str:
    payload = {
        "hint": hint,
        "ir": ir.model_dump(mode="json"),
        "runs": [
            {
                "artifact_path": run.artifact_path,
                "artifact_ref": run.artifact_ref,
                "output_sha256": run.output_sha256,
            }
            for run in tool_runs
        ],
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _read_compile_cache(cache_root: Path, cache_key: str) -> CompiledProgram | None:
    path = cache_root / f"{cache_key}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    segments = tuple(
        CompiledSegment(
            source=item["source"],
            scene_base=item["scene_base"],
            visual_kinds=tuple(VisualKind(kind) for kind in item["visual_kinds"]),
            duration_seconds=float(item["duration_seconds"]),
        )
        for item in data["segments"]
    )
    return CompiledProgram(segments=segments)


def _write_compile_cache(cache_root: Path, cache_key: str, program: CompiledProgram) -> None:
    cache_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "segments": [
            {
                "duration_seconds": segment.duration_seconds,
                "scene_base": segment.scene_base,
                "source": segment.source,
                "visual_kinds": [kind.value for kind in segment.visual_kinds],
            }
            for segment in program.segments
        ]
    }
    (cache_root / f"{cache_key}.json").write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _compile_animation_ir(
    ir: AnimationIR,
    tool_runs: tuple[ToolRun, ...],
    hint: str,
) -> CompiledProgram:
    validate_animation_ir(ir, tool_runs)
    backend = renderer_registry.require(hint)
    if not ir.data:
        raise UnsupportedFeature("AnimationIR requires tool data")
    scene_base = backend.select_scene_base(ir)
    ctx = backend.begin(ir, scene_base, tool_runs)
    for dataset in ir.data:
        ctx.register_data(dataset)
    for state in ir.states:
        ctx.emit_state(state)
    for obj in ir.objects:
        ctx.emit_object(obj)
    for binding in ir.bindings:
        ctx.emit_binding(binding)
    ctx.emit_timeline(ir.timeline)
    ctx.emit_camera(ir.camera)
    source = ctx.finish()
    if "lambda" in source:
        raise UnsupportedFeature("compiler emitted lambda")
    kind = (
        VisualKind.THREE_D
        if scene_base in {"ThreeDScene", "Web3DScene"}
        else VisualKind.FUNCTION
    )
    return CompiledProgram(
        segments=(
            CompiledSegment(
                source=source,
                scene_base=scene_base,
                visual_kinds=(kind,),
                duration_seconds=ctx.duration_seconds,
            ),
        )
    )


@dataclass
class ManimEmitContext:
    ir: AnimationIR
    scene_base: str
    tool_runs: tuple[ToolRun, ...]
    _runs: dict[str, ToolRun] = field(init=False)
    _data: dict[str, RegisteredData] = field(default_factory=dict)
    _manim_imports: set[str] = field(default_factory=set)
    _data_lines: list[str] = field(default_factory=list)
    _state_lines: list[str] = field(default_factory=list)
    _object_lines: list[str] = field(default_factory=list)
    _binding_lines: list[str] = field(default_factory=list)
    _timeline_lines: list[str] = field(default_factory=list)
    _camera_prefix: list[str] = field(default_factory=list)
    _camera_suffix: list[str] = field(default_factory=list)
    _object_vars: dict[str, str] = field(default_factory=dict)
    _trackers: dict[str, str] = field(default_factory=dict)
    _state_end: dict[str, str] = field(default_factory=dict)
    _bound_objects: set[str] = field(default_factory=set)
    _unpacked: set[str] = field(default_factory=set)
    _arrays: dict[tuple[str, str], str] = field(default_factory=dict)
    _polyline_emitted: bool = False
    _axes_var: str | None = None
    _always_add: list[str] = field(default_factory=list)
    _consumed_series: set[str] = field(default_factory=set)
    duration_seconds: float = 0.0

    def __post_init__(self) -> None:
        self._runs = {item.artifact_ref: item for item in self.tool_runs}
        self._bound_objects = {binding.target.split(".", 1)[0] for binding in self.ir.bindings}
        self._use("Text", "UP", "YELLOW")
        self._use(self.scene_base)

    def register_data(self, dataset: DataRef) -> None:
        run = self._runs.get(dataset.artifact_ref)
        if run is None:
            raise UnsupportedFeature("ToolRun artifact is missing")
        asset = f"/input/assets/{run.output_sha256}.npz"
        packed_var = "packed" if not self._data else f"packed_{dataset.id}"
        keys: set[str] = set()
        shapes: dict[str, tuple[int, ...]] = {}
        packed = np.load(run.artifact_path, allow_pickle=False)
        try:
            keys = set(packed.files)
            shapes = {name: tuple(int(n) for n in packed[name].shape) for name in packed.files}
        finally:
            packed.close()
        self._data[dataset.id] = RegisteredData(
            spec=dataset,
            packed_var=packed_var,
            asset=asset,
            keys=frozenset(keys),
            shapes=shapes,
        )
        self._data_lines.append(f"{packed_var} = np.load({asset!r}, allow_pickle=False)")

    def emit_state(self, state: StateSpec) -> None:
        self._use("ValueTracker")
        var = f"tracker_{state.id}"
        self._trackers[state.id] = var
        initial = 0 if state.type is StateType.INTEGER else state.initial
        self._state_lines.append(f"{var} = ValueTracker({int(initial) if float(initial).is_integer() else initial})")

    def emit_object(self, obj: AnimObject) -> None:
        handler = _OBJECT_HANDLERS.get(obj.type)
        if handler is None:
            raise UnsupportedFeature(f"object type {obj.type.value} is not lowered")
        handler(self, obj)

    def emit_binding(self, binding: AnimBinding) -> None:
        if binding.source.op is BindingOp.IDENTITY:
            return
        if binding.source.op is not BindingOp.SAMPLE:
            raise UnsupportedFeature(f"binding op {binding.source.op.value} is not lowered")
        target_id = binding.target.split(".", 1)[0]
        obj = next((item for item in self.ir.objects if item.id == target_id), None)
        if obj is None:
            raise UnsupportedFeature(f"binding target {target_id} is missing")
        data_id = binding.source.data or obj.data_ref
        state_id = binding.source.state
        if data_id is None or state_id is None:
            raise UnsupportedFeature("sample binding requires data and state")
        handler = _BINDING_HANDLERS.get(obj.type)
        if handler is None:
            raise UnsupportedFeature(f"no sample lowering for {obj.type.value}")
        handler(self, obj, data_id, state_id)

    def emit_timeline(self, ops: tuple[TimelineOp, ...]) -> None:
        ambient = next(
            (op for op in self.ir.camera if op.op is CameraOpKind.AMBIENT_ROTATE),
            None,
        )
        started_ambient = False
        for op in ops:
            if op.op is TimelineOpKind.CREATE:
                self._add_targets(op.targets)
            elif op.op is TimelineOpKind.REVEAL:
                self._add_targets(op.targets)
                self._timeline_lines.append("self.wait(1.0)")
                self.duration_seconds += 1.0
            elif op.op is TimelineOpKind.HIGHLIGHT:
                target = op.target or (op.targets[0] if op.targets else None)
                if target is None or target not in self._object_vars:
                    raise UnsupportedFeature("highlight target is missing")
                self._use("FadeIn")
                self._timeline_lines.append(
                    f"self.play(FadeIn({self._object_vars[target]}), run_time=1.2)"
                )
                self._timeline_lines.append("self.wait(2.0)")
                self.duration_seconds += 3.2
            elif op.op is TimelineOpKind.WAIT:
                wait_time = op.wait_time or op.duration
                self._timeline_lines.append(f"self.wait({wait_time})")
                self.duration_seconds += wait_time
            elif op.op in {
                TimelineOpKind.ANIMATE_STATE,
                TimelineOpKind.TRACE,
                TimelineOpKind.COMPARE,
            }:
                if ambient is not None and not started_ambient:
                    self._use_camera_rotation(ambient)
                    started_ambient = True
                self._play_state(op)
            else:
                raise UnsupportedFeature(f"timeline op {op.op.value} is not lowered")
        if started_ambient:
            self._timeline_lines.append("self.stop_ambient_camera_rotation()")

    def emit_camera(self, ops: tuple[AnimCameraOp, ...]) -> None:
        for op in ops:
            if op.op is CameraOpKind.STATIC:
                continue
            if op.op is CameraOpKind.SET_ORIENTATION:
                phi = op.phi_degrees if op.phi_degrees is not None else 70.0
                theta = op.theta_degrees if op.theta_degrees is not None else 45.0
                self._camera_prefix.append(
                    "self.set_camera_orientation("
                    f"phi={phi} * 3.14159265 / 180, theta={theta} * 3.14159265 / 180)"
                )
            elif op.op is CameraOpKind.AMBIENT_ROTATE:
                continue
            elif op.op is CameraOpKind.ZOOM:
                if self.scene_base != "MovingCameraScene":
                    if any(item.strategy is FallbackStrategy.FIXED_CAMERA for item in self.ir.fallbacks):
                        continue
                    raise UnsupportedFeature("zoom requires MovingCameraScene")
                self._emit_zoom(op)
            elif op.op is CameraOpKind.FOLLOW:
                if any(item.strategy is FallbackStrategy.FIXED_CAMERA for item in self.ir.fallbacks):
                    continue
                raise UnsupportedFeature("camera follow is not lowered")
            else:
                raise UnsupportedFeature(f"camera op {op.op.value} is not lowered")

    def finish(self) -> str:
        body: list[str] = []
        body.extend(self._data_lines)
        body.extend(self._camera_prefix)
        body.extend(self._state_lines)
        body.extend(self._object_lines)
        body.extend(self._binding_lines)
        if self.scene_base == "ThreeDScene" and "title" in self._object_vars:
            body.append("self.add_fixed_in_frame_mobjects(title)")
        body.extend(self._timeline_lines)
        body.extend(self._camera_suffix)
        indented = ["        " + line if line else "" for line in body]
        symbols = [name for name in _IMPORT_ORDER if name in self._manim_imports]
        extras = sorted(self._manim_imports.difference(_IMPORT_ORDER))
        imported = ", ".join([*symbols, *extras])
        return "\n".join(
            [
                "import numpy as np",
                f"from manim import {imported}",
                "",
                f"class GeneratedScene({self.scene_base}):",
                "    def construct(self):",
                *indented,
                "",
            ]
        )

    def _use(self, *names: str) -> None:
        self._manim_imports.update(names)

    def _color(self, obj: AnimObject, default: str) -> str:
        name = obj.color or default
        self._use(name)
        return name

    def _has_key(self, data_id: str, key: str) -> bool:
        return key in self._data[data_id].keys

    def _shape(self, data_id: str, key: str) -> tuple[int, ...]:
        return self._data[data_id].shapes.get(key, ())

    def _unpack(self, data_id: str, key: str, alias: str | None = None) -> str:
        cached = self._arrays.get((data_id, key))
        if cached is not None:
            return cached
        name = alias or key
        if name in {item.id for item in self.ir.objects}:
            name = f"{key}_arr"
        packed = self._data[data_id].packed_var
        self._object_lines.append(f"{name} = {packed}[{key!r}]")
        self._arrays[(data_id, key)] = name
        self._unpacked.add(name)
        return name

    def _ensure_polyline(self) -> None:
        if self._polyline_emitted:
            return
        self._use("Line", "VGroup")
        self._object_lines.extend(
            [
                "def polyline(xs, ys, color):",
                "    pieces = []",
                "    previous = None",
                "    for index in range(len(xs)):",
                "        point = axes.c2p(float(xs[index]), float(ys[index]))",
                "        if previous is not None:",
                "            pieces.append(Line(previous, point, color=color))",
                "        previous = point",
                "    return VGroup(*pieces)",
            ]
        )
        self._polyline_emitted = True

    def _ensure_2d_axes(self, data_id: str) -> None:
        if self._axes_var is not None:
            return
        self._use("Axes")
        self._axes_var = "axes"
        info = self._data[data_id]
        if "partials" in info.keys or "square" in info.keys:
            self._object_lines.append(
                "axes = Axes(x_range=[-3.5, 3.5, 1], y_range=[-1.6, 1.6, 0.5], x_length=10, y_length=4.6, tips=False)"
            )
        elif "temperature" in info.keys:
            ts = self._unpack(data_id, "t", "ts")
            temperature = self._unpack(data_id, "temperature")
            pressure = self._unpack(data_id, "pressure")
            self._object_lines.extend(
                [
                    f"t_min = float({ts}[0])",
                    f"t_max = float({ts}[len({ts}) - 1])",
                    f"temp_lo = float(min({temperature}))",
                    f"pressure_lo = float(min({pressure}))",
                    "if pressure_lo < 0.001:",
                    "    pressure_lo = 1.0",
                    "p_scale = temp_lo / pressure_lo",
                    f"pressure_plot = {pressure} * p_scale",
                    "y_lo = min(temp_lo, float(min(pressure_plot))) - 2.0",
                    f"y_hi = max(float(max({temperature})), float(max(pressure_plot))) + 2.0",
                    "axes = Axes(x_range=[t_min, t_max, 50], y_range=[y_lo, y_hi, 5], x_length=10, y_length=4.4, tips=False)",
                    "axes.add_coordinates()",
                ]
            )
        else:
            self._unpack(data_id, "t", "ts")
            self._object_lines.extend(
                [
                    "t_lo = float(ts[0])",
                    "t_hi = float(ts[len(ts) - 1])",
                    "axes = Axes(x_range=[t_lo, t_hi, 2], y_range=[-0.2, 1.8, 0.5], x_length=10, y_length=4.6, tips=False)",
                ]
            )
            if self._shape(data_id, "y")[:1] and len(self._shape(data_id, "y")) == 2:
                self._use("DashedLine", "GRAY")
                self._object_lines.append(
                    "ref = DashedLine(axes.c2p(t_lo, 1.0), axes.c2p(t_hi, 1.0), color=GRAY)"
                )
                self._always_add.append("ref")
        self._always_add.append("axes")

    def _ensure_3d_axes(self) -> None:
        if self._axes_var is not None:
            return
        self._use("ThreeDAxes")
        self._axes_var = "axes"
        self._object_lines.append(
            "axes = ThreeDAxes(x_range=[-24, 24, 8], y_range=[-24, 24, 8], z_range=[0, 48, 8], x_length=6, y_length=6, z_length=4)"
        )
        self._always_add.append("axes")

    def _add_targets(self, targets: tuple[str, ...]) -> None:
        names: list[str] = []
        for extra in self._always_add:
            if extra not in names:
                names.append(extra)
        if "title" in self._object_vars and "title" not in names:
            names.insert(0, "title")
        for target in targets:
            var = self._object_vars.get(target)
            if var is not None and var not in names:
                names.append(var)
        if not names:
            return
        self._timeline_lines.append(f"self.add({', '.join(names)})")

    def _play_state(self, op: TimelineOp) -> None:
        self._use("linear")
        state_id = op.target if op.target in self._trackers else None
        if state_id is None:
            if op.target in self._object_vars:
                state_id = next(
                    (
                        binding.source.state
                        for binding in self.ir.bindings
                        if binding.target.split(".", 1)[0] == op.target and binding.source.state
                    ),
                    None,
                )
            if state_id is None and self.ir.states:
                state_id = self.ir.states[0].id
        if state_id is None or state_id not in self._trackers:
            raise UnsupportedFeature("timeline is missing a state tracker")
        end_expr = self._state_end.get(state_id, "1")
        duration = op.duration
        self._timeline_lines.append(
            f"self.play({self._trackers[state_id]}.animate.set_value({end_expr}), run_time={duration}, rate_func=linear)"
        )
        self.duration_seconds += duration

    def _use_camera_rotation(self, op: AnimCameraOp) -> None:
        rate = op.rate if op.rate is not None else 0.08
        self._timeline_lines.append(f"self.begin_ambient_camera_rotation(rate={rate})")

    def _emit_zoom(self, op: AnimCameraOp) -> None:
        run_time = op.run_time
        if any(item.type is AssertionType.GIBBS_OVERSHOOT for item in self.ir.assertions):
            self._camera_suffix.append(
                f"self.play(self.camera.frame.animate.scale(0.32).move_to(axes.c2p(0.45, 1.12)), run_time={run_time})"
            )
        else:
            self._camera_suffix.append(
                f"self.play(self.camera.frame.animate.scale(0.5), run_time={run_time})"
            )
        self._camera_suffix.append("self.wait(1.2)")
        self.duration_seconds += run_time + 1.2

    def _title(self, obj: AnimObject) -> None:
        text = obj.text or self.ir.goal
        self._object_vars[obj.id] = "title"
        self._object_lines.append(
            f"title = Text({_text_literal(text)}, font='{_TITLE_FONT}', font_size=32, color={self._color(obj, 'YELLOW')}).to_edge(UP)"
        )

    def _scalar_field(self, obj: AnimObject) -> None:
        if obj.id in self._bound_objects:
            return
        raise UnsupportedFeature("scalar_field requires a sample binding")

    def _graph(self, obj: AnimObject) -> None:
        if obj.data_ref is None:
            raise UnsupportedFeature("graph requires data_ref")
        info = self._data[obj.data_ref]
        sibling_bound = any(
            other.id in self._bound_objects
            for other in self.ir.objects
            if other.type is ObjectType.GRAPH
            and other.data_ref == obj.data_ref
            and other.id != obj.id
        )
        if (
            obj.id not in self._bound_objects
            and sibling_bound
            and "y" in info.keys
            and len(self._shape(obj.data_ref, "y")) == 2
        ):
            return
        self._ensure_2d_axes(obj.data_ref)
        if obj.id in self._bound_objects:
            return
        if obj.data_ref in self._consumed_series:
            return
        if "square" in info.keys and obj.id == "square":
            xs = self._unpack(obj.data_ref, "x", "xs")
            square = self._unpack(obj.data_ref, "square")
            self._ensure_polyline()
            self._object_vars[obj.id] = obj.id
            self._object_lines.append(
                f"{obj.id} = polyline({xs}, {square}, {self._color(obj, 'GRAY')})"
            )
            return
        if "y" in info.keys and len(self._shape(obj.data_ref, "y")) == 2:
            self._emit_series_comparison(obj)
            return
        if obj.id in info.keys:
            xs_key = "x" if "x" in info.keys else "t"
            xs_alias = "xs" if xs_key == "x" else "ts"
            xs = self._unpack(obj.data_ref, xs_key, xs_alias)
            values = self._unpack(obj.data_ref, obj.id)
            self._ensure_polyline()
            self._object_vars[obj.id] = obj.id
            self._object_lines.append(
                f"{obj.id} = polyline({xs}, {values}, {self._color(obj, 'BLUE')})"
            )
            return
        raise UnsupportedFeature(f"graph {obj.id} has no array to lower")

    def _emit_series_comparison(self, obj: AnimObject) -> None:
        data_id = obj.data_ref
        assert data_id is not None
        self._unpack(data_id, "t", "ts")
        self._unpack(data_id, "y", "ys")
        rows = self._shape(data_id, "y")[0]
        self._use("Line", "VGroup", "always_redraw", "BLUE", "GREEN", "ORANGE")
        colors = ("BLUE", "GREEN", "ORANGE", "YELLOW", "RED")
        tracker = self._trackers[self.ir.states[0].id] if self.ir.states else "tracker_t"
        self._state_end[self.ir.states[0].id] = "len(ts) - 1"
        if tracker in {line.split(" = ", 1)[0] for line in self._state_lines}:
            self._state_lines[:] = [
                line.replace("ValueTracker(0)", "ValueTracker(2)") if line.startswith(tracker) else line
                for line in self._state_lines
            ]
        curve_vars: list[str] = []
        for index in range(rows):
            color = colors[index % len(colors)]
            fn_name = f"redraw_curve_{index}"
            var = f"curve_{index}"
            self._object_lines.extend(
                [
                    f"def {fn_name}():",
                    f"    last = int({tracker}.get_value())",
                    "    if last < 2:",
                    "        last = 2",
                    "    if last > len(ts) - 1:",
                    "        last = len(ts) - 1",
                    "    pieces = []",
                    "    previous = None",
                    "    for index in range(last):",
                    f"        point = axes.c2p(float(ts[index]), float(ys[{index}][index]))",
                    "        if previous is not None:",
                    f"            pieces.append(Line(previous, point, color={color}))",
                    "        previous = point",
                    "    return VGroup(*pieces)",
                    f"{var} = always_redraw({fn_name})",
                ]
            )
            curve_vars.append(var)
        self._object_vars[obj.id] = curve_vars[0] if len(curve_vars) == 1 else obj.id
        if len(curve_vars) > 1:
            self._object_lines.append(f"{obj.id} = VGroup({', '.join(curve_vars)})")
            self._object_vars[obj.id] = obj.id
        self._consumed_series.add(data_id)

    def _trajectory_set(self, obj: AnimObject) -> None:
        if obj.id in self._bound_objects:
            return
        raise UnsupportedFeature("trajectory_set requires a sample binding")

    def _timeseries(self, obj: AnimObject) -> None:
        if obj.data_ref is None:
            raise UnsupportedFeature("timeseries requires data_ref")
        self._ensure_2d_axes(obj.data_ref)
        self._unpack(obj.data_ref, "t", "ts")
        self._ensure_polyline()
        if obj.id in {"temp", "temperature"}:
            self._object_vars[obj.id] = "temp_graph"
            self._object_lines.append(
                f"temp_graph = polyline(ts, temperature, {self._color(obj, 'RED')})"
            )
            return
        if obj.id == "pressure":
            self._object_vars[obj.id] = "pressure_graph"
            self._object_lines.append(
                f"pressure_graph = polyline(ts, pressure_plot, {self._color(obj, 'BLUE')})"
            )
            return
        raise UnsupportedFeature(f"timeseries {obj.id} is not lowered")

    def _region(self, obj: AnimObject) -> None:
        if obj.data_ref is None:
            raise UnsupportedFeature("region requires data_ref")
        self._ensure_2d_axes(obj.data_ref)
        self._unpack(obj.data_ref, "t", "ts")
        self._unpack(obj.data_ref, "mask")
        self._use("Rectangle", "YELLOW")
        self._object_vars[obj.id] = obj.id
        self._object_lines.extend(
            [
                "left_t = float(ts[0])",
                "right_t = float(ts[0])",
                "for index in range(len(mask)):",
                "    if int(mask[index]) == 1:",
                "        left_t = float(ts[index])",
                "        break",
                "for index in range(len(mask)):",
                "    last = len(mask) - 1 - index",
                "    if int(mask[last]) == 1:",
                "        right_t = float(ts[last])",
                "        break",
                "mid_y = (y_lo + y_hi) / 2.0",
                "left_point = axes.c2p(left_t, mid_y)",
                "right_point = axes.c2p(right_t, mid_y)",
                "width = float(right_point[0]) - float(left_point[0])",
                "if width < 0.25:",
                "    width = 0.25",
                f"{obj.id} = Rectangle(width=width, height=4.2, color={self._color(obj, 'YELLOW')})",
                f"{obj.id}.move_to(axes.c2p((left_t + right_t) / 2.0, mid_y))",
                f"{obj.id}.set_stroke({self._color(obj, 'YELLOW')})",
                f"{obj.id}.set_fill({self._color(obj, 'YELLOW')}, opacity=0.2)",
            ]
        )

    def _path(self, obj: AnimObject) -> None:
        if obj.data_ref is None:
            raise UnsupportedFeature("path requires data_ref")
        curve = self._unpack(obj.data_ref, "curve")
        self._use("Line", "VGroup", "WHITE")
        self._object_vars[obj.id] = obj.id
        self._object_lines.extend(
            [
                "def scaled(point):",
                "    return [float(point[0]), float(point[1]), float(point[2]) * 0.35]",
                "pieces = []",
                "previous = None",
                f"for index in range(len({curve})):",
                f"    point = scaled({curve}[index])",
                "    if previous is not None:",
                f"        pieces.append(Line(previous, point, color={self._color(obj, 'WHITE')}))",
                "    previous = point",
                f"{obj.id} = VGroup(*pieces)",
            ]
        )
        self._unpacked.add("scaled")

    def _arrow_frame(self, obj: AnimObject) -> None:
        if obj.id in self._bound_objects:
            return
        raise UnsupportedFeature("arrow_frame requires a sample binding")

    def _bind_scalar_field(self, obj: AnimObject, data_id: str, state_id: str) -> None:
        self._unpack(data_id, "rgb", "frames")
        self._use("ImageMobject", "always_redraw", "DOWN")
        tracker = self._trackers[state_id]
        fn_name = f"redraw_{obj.id}"
        self._state_end[state_id] = "len(frames) - 1"
        self._object_vars[obj.id] = obj.id
        self._binding_lines.extend(
            [
                f"def {fn_name}():",
                f"    index = int({tracker}.get_value())",
                "    last = len(frames) - 1",
                "    if index < 0:",
                "        index = 0",
                "    if index > last:",
                "        index = last",
                "    image = ImageMobject(frames[index])",
                "    image.set_height(6.0)",
                "    image.shift(DOWN * 0.35)",
                "    return image",
                f"{obj.id} = always_redraw({fn_name})",
            ]
        )

    def _bind_graph(self, obj: AnimObject, data_id: str, state_id: str) -> None:
        self._ensure_2d_axes(data_id)
        info = self._data[data_id]
        tracker = self._trackers[state_id]
        if "partials" in info.keys:
            xs = self._unpack(data_id, "x", "xs")
            partials = self._unpack(data_id, "partials")
            self._ensure_polyline()
            self._use("always_redraw", "BLUE")
            fn_name = f"redraw_{obj.id}"
            self._state_end[state_id] = f"len({partials}) - 1"
            self._object_vars[obj.id] = obj.id
            self._binding_lines.extend(
                [
                    f"def {fn_name}():",
                    f"    index = int({tracker}.get_value())",
                    f"    last = len({partials}) - 1",
                    "    if index < 0:",
                    "        index = 0",
                    "    if index > last:",
                    "        index = last",
                    f"    return polyline({xs}, {partials}[index], {self._color(obj, 'BLUE')})",
                    f"{obj.id} = always_redraw({fn_name})",
                ]
            )
            return
        if "y" in info.keys and len(self._shape(data_id, "y")) == 2:
            if data_id not in self._consumed_series:
                self._emit_series_comparison(obj)
            return
        raise UnsupportedFeature(f"graph sample for {obj.id} is not lowered")

    def _bind_trajectory_set(self, obj: AnimObject, data_id: str, state_id: str) -> None:
        self._ensure_3d_axes()
        paths = self._unpack(data_id, "paths")
        self._use("Line", "VGroup", "Dot", "always_redraw", "BLUE", "RED", "GREEN")
        tracker = self._trackers[state_id]
        rows = self._shape(data_id, "paths")[0] or 3
        self._state_end[state_id] = f"len({paths}[0]) - 1"
        if any(line.startswith(tracker) for line in self._state_lines):
            self._state_lines[:] = [
                line.replace("ValueTracker(0)", "ValueTracker(1)") if line.startswith(tracker) else line
                for line in self._state_lines
            ]
        colors = ("BLUE", "RED", "GREEN", "YELLOW", "ORANGE")
        self._binding_lines.extend(
            [
                "def scaled(point):",
                "    return [float(point[0]) * 0.12, float(point[1]) * 0.12, float(point[2]) * 0.12 - 1.5]",
            ]
        )
        trace_vars: list[str] = []
        for index in range(rows):
            color = colors[index % len(colors)]
            fn_name = f"redraw_trace_{index}"
            var = f"trace_{index}"
            self._binding_lines.extend(
                [
                    f"def {fn_name}():",
                    f"    last = int({tracker}.get_value())",
                    "    if last < 1:",
                    "        last = 1",
                    "    pieces = []",
                    "    previous = None",
                    "    for index in range(last):",
                    f"        point = scaled({paths}[{index}][index])",
                    "        if previous is not None:",
                    f"            pieces.append(Line(previous, point, color={color}))",
                    "        previous = point",
                    "    group = VGroup(*pieces)",
                    f"    group.add(Dot(point=previous, color={color}, radius=0.06))",
                    "    return group",
                    f"{var} = always_redraw({fn_name})",
                ]
            )
            trace_vars.append(var)
        self._object_vars[obj.id] = obj.id
        self._binding_lines.append(f"{obj.id} = VGroup({', '.join(trace_vars)})")

    def _bind_arrow_frame(self, obj: AnimObject, data_id: str, state_id: str) -> None:
        curve = self._unpack(data_id, "curve")
        if "scaled" not in self._unpacked:
            self._object_lines.extend(
                [
                    "def scaled(point):",
                    "    return [float(point[0]), float(point[1]), float(point[2]) * 0.35]",
                ]
            )
            self._unpacked.add("scaled")
        tangent = self._unpack(data_id, "tangent")
        normal = self._unpack(data_id, "normal")
        binormal = self._unpack(data_id, "binormal")
        self._use("Arrow", "VGroup", "always_redraw", "RED", "GREEN", "BLUE")
        tracker = self._trackers[state_id]
        fn_name = f"redraw_{obj.id}"
        self._state_end[state_id] = f"len({curve}) - 1"
        self._object_vars[obj.id] = obj.id
        self._binding_lines.extend(
            [
                f"def {fn_name}():",
                f"    index = int({tracker}.get_value())",
                f"    last = len({curve}) - 1",
                "    if index < 0:",
                "        index = 0",
                "    if index > last:",
                "        index = last",
                f"    origin = scaled({curve}[index])",
                f"    t_end = [origin[0] + float({tangent}[index][0]), origin[1] + float({tangent}[index][1]), origin[2] + float({tangent}[index][2])]",
                f"    n_end = [origin[0] + float({normal}[index][0]), origin[1] + float({normal}[index][1]), origin[2] + float({normal}[index][2])]",
                f"    b_end = [origin[0] + float({binormal}[index][0]), origin[1] + float({binormal}[index][1]), origin[2] + float({binormal}[index][2])]",
                "    return VGroup(Arrow(origin, t_end, color=RED, buff=0), Arrow(origin, n_end, color=GREEN, buff=0), Arrow(origin, b_end, color=BLUE, buff=0))",
                f"{obj.id} = always_redraw({fn_name})",
            ]
        )


_OBJECT_HANDLERS = {
    ObjectType.TITLE: ManimEmitContext._title,
    ObjectType.SCALAR_FIELD: ManimEmitContext._scalar_field,
    ObjectType.GRAPH: ManimEmitContext._graph,
    ObjectType.TRAJECTORY_SET: ManimEmitContext._trajectory_set,
    ObjectType.TIMESERIES: ManimEmitContext._timeseries,
    ObjectType.REGION: ManimEmitContext._region,
    ObjectType.PATH: ManimEmitContext._path,
    ObjectType.ARROW_FRAME: ManimEmitContext._arrow_frame,
}

_BINDING_HANDLERS = {
    ObjectType.SCALAR_FIELD: ManimEmitContext._bind_scalar_field,
    ObjectType.GRAPH: ManimEmitContext._bind_graph,
    ObjectType.TRAJECTORY_SET: ManimEmitContext._bind_trajectory_set,
    ObjectType.ARROW_FRAME: ManimEmitContext._bind_arrow_frame,
}
