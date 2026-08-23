"""Fill AnimationIR 2.0 from intent + tool artifacts. No Python in IR."""

from __future__ import annotations

import math

from manim_workbench_contracts import IntentSpec, ToolOp, ToolRun
from manim_workbench_contracts.animation_ir import (
    AnimAssertion,
    AnimationIR,
    AnimBinding,
    AnimCameraOp,
    AnimFallback,
    AnimObject,
    AssertionType,
    BindingOp,
    BindingSource,
    CameraOpKind,
    DataKind,
    DataRef,
    FallbackStrategy,
    ObjectType,
    SceneHint,
    StateSpec,
    StateType,
    TimelineOp,
    TimelineOpKind,
    VisualPattern,
)


def direct_ir(intent: IntentSpec, tool_runs: tuple[ToolRun, ...]) -> AnimationIR:
    if not tool_runs:
        raise ValueError("Visual Director requires ToolRun artifacts")
    primary = tool_runs[0]
    builders = {
        ToolOp.WAVE2D_SUPERPOSITION: _wave,
        ToolOp.FOURIER_SQUARE_WAVE: _fourier,
        ToolOp.LORENZ_ENSEMBLE: _lorenz,
        ToolOp.PID_STEP_RESPONSE: _pid,
        ToolOp.CSV_ANOMALY: _csv,
        ToolOp.FRENET_FRAME: _frenet,
        ToolOp.ODE_COMPARE: _ode,
    }
    builder = builders.get(primary.op)
    if builder is None:
        raise ValueError(f"no visual pattern for {primary.op}")
    return _retime_ir(builder(intent, primary), intent.output_duration_seconds)


_ACTIVE_TIMELINE_OPS = {
    TimelineOpKind.ANIMATE_STATE,
    TimelineOpKind.TRACE,
    TimelineOpKind.COMPARE,
}
# Cairo/FFmpeg final renders can exceed the 2 GiB sandbox limit when one
# animation spans hundreds of 1080p frames. Keep deterministic active chunks
# short while preserving the requested aggregate duration.
_MAX_ACTIVE_OP_SECONDS = 3.0


def _retime_ir(ir: AnimationIR, target_duration_seconds: float) -> AnimationIR:
    """Fit deterministic active animation to the requested duration without static padding."""
    active = tuple(item for item in ir.timeline if item.op in _ACTIVE_TIMELINE_OPS)
    if not active:
        return ir
    fixed_seconds = sum(_fixed_timeline_seconds(item) for item in ir.timeline)
    fixed_seconds += sum(item.run_time + 1.2 for item in ir.camera if item.op is CameraOpKind.ZOOM)
    available = target_duration_seconds - fixed_seconds
    if available <= 0:
        raise ValueError("target duration is too short for the selected visual pattern")
    total_weight = sum(item.duration for item in active)
    retimed: list[TimelineOp] = []
    for item in ir.timeline:
        if item.op not in _ACTIVE_TIMELINE_OPS:
            retimed.append(item)
            continue
        duration = available * item.duration / total_weight
        chunks = max(1, math.ceil(duration / _MAX_ACTIVE_OP_SECONDS))
        for index in range(chunks):
            retimed.append(
                item.model_copy(
                    update={
                        "duration": duration / chunks,
                        "to": (index + 1) / chunks,
                    }
                )
            )
    return ir.model_copy(update={"timeline": tuple(retimed)})


def _fixed_timeline_seconds(item: TimelineOp) -> float:
    if item.op is TimelineOpKind.REVEAL:
        return 1.0
    if item.op is TimelineOpKind.HIGHLIGHT:
        return 3.2
    if item.op is TimelineOpKind.WAIT:
        return item.wait_time or item.duration
    return 0.0


def _wave(intent: IntentSpec, run: ToolRun) -> AnimationIR:
    return AnimationIR(
        domain=intent.domain.value,
        goal=intent.goal,
        pattern=VisualPattern.FIELD_EVOLUTION,
        scene=SceneHint(dimension="2d"),
        data=(
            DataRef(
                id="field",
                kind=DataKind.ARRAY,
                artifact_ref=run.artifact_ref,
                output_sha256=run.output_sha256,
            ),
        ),
        states=(StateSpec(id="t", type=StateType.SCALAR, initial=0, range=(0.0, 1.0)),),
        objects=(
            AnimObject(id="title", type=ObjectType.TITLE, text="二维波包碰撞干涉", color="YELLOW"),
            AnimObject(id="heatmap", type=ObjectType.SCALAR_FIELD, data_ref="field"),
        ),
        bindings=(
            AnimBinding(
                target="heatmap.frame",
                source=BindingSource(op=BindingOp.SAMPLE, data="field", state="t"),
            ),
        ),
        timeline=(
            TimelineOp(op=TimelineOpKind.CREATE, targets=("title", "heatmap"), duration=0.8),
            TimelineOp(op=TimelineOpKind.ANIMATE_STATE, target="t", to=1.0, duration=9.5),
        ),
        assertions=(AnimAssertion(type=AssertionType.LINEAR_SUPERPOSITION, target="heatmap"),),
        fallbacks=(
            AnimFallback(on="live_field_kernel", strategy=FallbackStrategy.PRECOMPUTED_ONLY),
        ),
    )


def _fourier(intent: IntentSpec, run: ToolRun) -> AnimationIR:
    return AnimationIR(
        domain=intent.domain.value,
        goal=intent.goal,
        pattern=VisualPattern.COMPARISON,
        data=(
            DataRef(
                id="series",
                kind=DataKind.SERIES,
                artifact_ref=run.artifact_ref,
                output_sha256=run.output_sha256,
            ),
        ),
        states=(StateSpec(id="n", type=StateType.INTEGER, initial=0, range=(0.0, 1.0)),),
        objects=(
            AnimObject(
                id="title",
                type=ObjectType.TITLE,
                text="傅里叶逼近与 Gibbs",
                color="YELLOW",
            ),
            AnimObject(id="square", type=ObjectType.GRAPH, data_ref="series", color="GRAY"),
            AnimObject(id="partial", type=ObjectType.GRAPH, data_ref="series", color="BLUE"),
        ),
        bindings=(
            AnimBinding(
                target="partial.data",
                source=BindingSource(op=BindingOp.SAMPLE, data="series", state="n"),
            ),
        ),
        timeline=(
            TimelineOp(
                op=TimelineOpKind.CREATE,
                targets=("title", "square", "partial"),
                duration=0.8,
            ),
            TimelineOp(op=TimelineOpKind.ANIMATE_STATE, target="n", to=1.0, duration=8.0),
        ),
        camera=(AnimCameraOp(op=CameraOpKind.ZOOM, target="partial", run_time=2.2),),
        assertions=(
            AnimAssertion(type=AssertionType.HARMONIC_COEFFICIENTS, target="partial"),
            AnimAssertion(type=AssertionType.GIBBS_OVERSHOOT, target="partial"),
        ),
        fallbacks=(AnimFallback(on="camera_unsupported", strategy=FallbackStrategy.FIXED_CAMERA),),
    )


def _lorenz(intent: IntentSpec, run: ToolRun) -> AnimationIR:
    return AnimationIR(
        domain=intent.domain.value,
        goal=intent.goal,
        pattern=VisualPattern.THREED_ORBIT,
        scene=SceneHint(dimension="3d"),
        data=(
            DataRef(
                id="traj3",
                kind=DataKind.TRAJECTORY_SET,
                artifact_ref=run.artifact_ref,
                output_sha256=run.output_sha256,
            ),
        ),
        states=(StateSpec(id="t", type=StateType.SCALAR, initial=0, range=(0.0, 1.0)),),
        objects=(
            AnimObject(id="title", type=ObjectType.TITLE, text="Lorenz 初值敏感", color="YELLOW"),
            AnimObject(id="paths", type=ObjectType.TRAJECTORY_SET, data_ref="traj3"),
        ),
        bindings=(
            AnimBinding(
                target="paths.position",
                source=BindingSource(op=BindingOp.SAMPLE, data="traj3", state="t"),
            ),
        ),
        timeline=(
            TimelineOp(op=TimelineOpKind.CREATE, targets=("title", "paths"), duration=0.6),
            TimelineOp(op=TimelineOpKind.TRACE, target="paths", duration=12.0),
        ),
        camera=(
            AnimCameraOp(op=CameraOpKind.SET_ORIENTATION, phi_degrees=70, theta_degrees=45),
            AnimCameraOp(op=CameraOpKind.AMBIENT_ROTATE, rate=0.08),
        ),
        assertions=(AnimAssertion(type=AssertionType.TRAJECTORY_ERROR, target="paths"),),
        fallbacks=(AnimFallback(on="camera_unsupported", strategy=FallbackStrategy.FIXED_CAMERA),),
    )


def _pid(intent: IntentSpec, run: ToolRun) -> AnimationIR:
    return AnimationIR(
        domain=intent.domain.value,
        goal=intent.goal,
        pattern=VisualPattern.COMPARISON,
        data=(
            DataRef(
                id="responses",
                kind=DataKind.SERIES,
                artifact_ref=run.artifact_ref,
                output_sha256=run.output_sha256,
            ),
        ),
        states=(StateSpec(id="t", type=StateType.SCALAR, initial=0, range=(0.0, 1.0)),),
        objects=(
            AnimObject(id="title", type=ObjectType.TITLE, text="PID 阶跃响应对比", color="YELLOW"),
            AnimObject(id="y", type=ObjectType.GRAPH, data_ref="responses", color="BLUE"),
            AnimObject(id="u", type=ObjectType.GRAPH, data_ref="responses", color="ORANGE"),
        ),
        bindings=(
            AnimBinding(
                target="y.data",
                source=BindingSource(op=BindingOp.SAMPLE, data="responses", state="t"),
            ),
        ),
        timeline=(
            TimelineOp(op=TimelineOpKind.CREATE, targets=("title", "y", "u"), duration=0.6),
            TimelineOp(op=TimelineOpKind.COMPARE, target="responses", duration=8.0),
        ),
        assertions=(AnimAssertion(type=AssertionType.METRIC_MATCH, fields=("overshoot",)),),
        fallbacks=(AnimFallback(on="continuous_gain", strategy=FallbackStrategy.DISCRETE_SAMPLES),),
    )


def _csv(intent: IntentSpec, run: ToolRun) -> AnimationIR:
    return AnimationIR(
        domain=intent.domain.value,
        goal=intent.goal,
        pattern=VisualPattern.DATA_ANOMALY,
        data=(
            DataRef(
                id="df",
                kind=DataKind.TABLE,
                artifact_ref=run.artifact_ref,
                output_sha256=run.output_sha256,
            ),
        ),
        states=(StateSpec(id="t", type=StateType.SCALAR, initial=0, range=(0.0, 1.0)),),
        objects=(
            AnimObject(id="title", type=ObjectType.TITLE, text="时序异常高亮", color="YELLOW"),
            AnimObject(id="temp", type=ObjectType.TIMESERIES, data_ref="df", color="RED"),
            AnimObject(id="pressure", type=ObjectType.TIMESERIES, data_ref="df", color="BLUE"),
            AnimObject(id="anomaly", type=ObjectType.REGION, data_ref="df", color="YELLOW"),
        ),
        bindings=(
            AnimBinding(
                target="temp.data",
                source=BindingSource(op=BindingOp.SAMPLE, data="df", state="t"),
            ),
            AnimBinding(
                target="pressure.data",
                source=BindingSource(op=BindingOp.SAMPLE, data="df", state="t"),
            ),
        ),
        timeline=(
            TimelineOp(op=TimelineOpKind.REVEAL, targets=("temp", "pressure"), duration=4.0),
            TimelineOp(op=TimelineOpKind.ANIMATE_STATE, target="t", to=1.0, duration=4.0),
            TimelineOp(op=TimelineOpKind.HIGHLIGHT, target="anomaly", duration=4.0),
        ),
        assertions=(AnimAssertion(type=AssertionType.DATA_FIDELITY, target="temp"),),
        fallbacks=(AnimFallback(on="missing_csv", strategy=FallbackStrategy.STATIC_FRAME),),
    )


def _frenet(intent: IntentSpec, run: ToolRun) -> AnimationIR:
    return AnimationIR(
        domain=intent.domain.value,
        goal=intent.goal,
        pattern=VisualPattern.TRAJECTORY_TRACE,
        scene=SceneHint(dimension="3d"),
        data=(
            DataRef(
                id="helix",
                kind=DataKind.TRAJECTORY,
                artifact_ref=run.artifact_ref,
                output_sha256=run.output_sha256,
            ),
        ),
        states=(StateSpec(id="s", type=StateType.SCALAR, initial=0, range=(0.0, 1.0)),),
        objects=(
            AnimObject(id="title", type=ObjectType.TITLE, text="Frenet 标架", color="YELLOW"),
            AnimObject(id="curve", type=ObjectType.PATH, data_ref="helix", color="WHITE"),
            AnimObject(id="frame", type=ObjectType.ARROW_FRAME, data_ref="helix"),
        ),
        bindings=(
            AnimBinding(
                target="frame.position",
                source=BindingSource(op=BindingOp.SAMPLE, data="helix", state="s"),
            ),
        ),
        timeline=(
            TimelineOp(op=TimelineOpKind.CREATE, targets=("title", "curve", "frame"), duration=0.6),
            TimelineOp(op=TimelineOpKind.TRACE, target="frame", duration=10.0),
        ),
        camera=(AnimCameraOp(op=CameraOpKind.SET_ORIENTATION, phi_degrees=65, theta_degrees=40),),
        assertions=(AnimAssertion(type=AssertionType.FRENET_ORTHONORMAL, target="frame"),),
        fallbacks=(AnimFallback(on="camera_unsupported", strategy=FallbackStrategy.FIXED_CAMERA),),
    )


def _ode(intent: IntentSpec, run: ToolRun) -> AnimationIR:
    return AnimationIR(
        domain=intent.domain.value,
        goal=intent.goal,
        pattern=VisualPattern.COMPARISON,
        data=(
            DataRef(
                id="compare",
                kind=DataKind.SERIES,
                artifact_ref=run.artifact_ref,
                output_sha256=run.output_sha256,
            ),
        ),
        states=(StateSpec(id="t", type=StateType.SCALAR, initial=0, range=(0.0, 1.0)),),
        objects=(
            AnimObject(
                id="title",
                type=ObjectType.TITLE,
                text="论文模型与实验对比",
                color="YELLOW",
            ),
            AnimObject(id="observed", type=ObjectType.GRAPH, data_ref="compare", color="BLUE"),
            AnimObject(id="predicted", type=ObjectType.GRAPH, data_ref="compare", color="ORANGE"),
        ),
        timeline=(
            TimelineOp(
                op=TimelineOpKind.CREATE,
                targets=("title", "observed", "predicted"),
                duration=0.6,
            ),
            TimelineOp(op=TimelineOpKind.COMPARE, target="compare", duration=8.0),
        ),
        assertions=(AnimAssertion(type=AssertionType.RESIDUAL_MATCHES_TOOL, target="predicted"),),
        fallbacks=(
            AnimFallback(on="low_equation_confidence", strategy=FallbackStrategy.STATIC_FRAME),
        ),
    )
