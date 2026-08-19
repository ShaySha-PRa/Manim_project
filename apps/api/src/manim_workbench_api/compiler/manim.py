"""Deterministic Manim lowering for AnimationIR 2.0. Never emits lambda."""

# Generated Scene source is stored as string literals; keep those lines intact.
# ruff: noqa: E501

from __future__ import annotations

from manim_workbench_contracts import ToolRun
from manim_workbench_contracts.animation_ir import AnimationIR, ObjectType, VisualPattern
from manim_workbench_contracts.ir import VisualKind

from manim_workbench_api.compiler.base import CompiledProgram, CompiledSegment, UnsupportedFeature

_TITLE_FONT = "Noto Sans CJK SC"


def _text_literal(value: str) -> str:
    return repr(value)


def compile_animation_ir(
    ir: AnimationIR,
    tool_runs: tuple[ToolRun, ...],
) -> CompiledProgram:
    if ir.scene.renderer_hint != "manim":
        raise UnsupportedFeature("only the Manim backend is available")
    runs = {item.artifact_ref: item for item in tool_runs}
    if not ir.data:
        raise UnsupportedFeature("AnimationIR requires tool data")
    primary = runs.get(ir.data[0].artifact_ref)
    if primary is None:
        raise UnsupportedFeature("ToolRun artifact is missing")
    asset = f"/input/assets/{primary.output_sha256}.npz"
    if ir.pattern is VisualPattern.FIELD_EVOLUTION:
        source = _compile_field(ir, asset)
        base = "Scene"
        kind = VisualKind.FUNCTION
        duration = 9.5
    elif ir.pattern is VisualPattern.COMPARISON and any(
        obj.type is ObjectType.GRAPH and obj.id == "partial" for obj in ir.objects
    ):
        source = _compile_fourier(ir, asset)
        base = "MovingCameraScene"
        kind = VisualKind.FUNCTION
        duration = 11.4
    elif ir.pattern is VisualPattern.COMPARISON:
        source = _compile_pid(ir, asset)
        base = "Scene"
        kind = VisualKind.FUNCTION
        duration = 8.0
    elif ir.pattern is VisualPattern.THREED_ORBIT:
        source = _compile_lorenz(ir, asset)
        base = "ThreeDScene"
        kind = VisualKind.THREE_D
        duration = 12.0
    elif ir.pattern is VisualPattern.DATA_ANOMALY:
        source = _compile_csv(ir, asset)
        base = "Scene"
        kind = VisualKind.FUNCTION
        duration = 8.0
    elif ir.pattern is VisualPattern.TRAJECTORY_TRACE:
        source = _compile_frenet(ir, asset)
        base = "ThreeDScene"
        kind = VisualKind.THREE_D
        duration = 10.0
    else:
        raise UnsupportedFeature(f"pattern {ir.pattern.value} is not lowered")
    if "lambda" in source:
        raise UnsupportedFeature("compiler emitted lambda")
    return CompiledProgram(
        segments=(
            CompiledSegment(
                source=source,
                scene_base=base,
                visual_kinds=(kind,),
                duration_seconds=duration,
            ),
        )
    )


def _title_line(ir: AnimationIR) -> str:
    title = next((obj.text for obj in ir.objects if obj.type is ObjectType.TITLE), ir.goal)
    return (
        f"        title = Text({_text_literal(title or ir.goal)}, font='{_TITLE_FONT}',"
        " font_size=32, color=YELLOW).to_edge(UP)"
    )


def _compile_field(ir: AnimationIR, asset: str) -> str:
    return "\n".join(
        [
            "import numpy as np",
            "from manim import Scene, Text, ImageMobject, ValueTracker, always_redraw, UP, DOWN, YELLOW, linear",
            "",
            "class GeneratedScene(Scene):",
            "    def construct(self):",
            f"        packed = np.load({asset!r}, allow_pickle=False)",
            '        frames = packed["rgb"]',
            "        tracker = ValueTracker(0)",
            _title_line(ir),
            "        def redraw_heatmap():",
            "            index = int(tracker.get_value())",
            "            last = len(frames) - 1",
            "            if index < 0:",
            "                index = 0",
            "            if index > last:",
            "                index = last",
            "            image = ImageMobject(frames[index])",
            "            image.set_height(6.0)",
            "            image.shift(DOWN * 0.35)",
            "            return image",
            "        heatmap = always_redraw(redraw_heatmap)",
            "        self.add(title, heatmap)",
            "        self.play(tracker.animate.set_value(len(frames) - 1), run_time=9.5, rate_func=linear)",
            "",
        ]
    )


def _compile_fourier(ir: AnimationIR, asset: str) -> str:
    return "\n".join(
        [
            "import numpy as np",
            "from manim import MovingCameraScene, Text, Axes, Line, VGroup, ValueTracker, always_redraw, UP, YELLOW, BLUE, GRAY, linear",
            "",
            "class GeneratedScene(MovingCameraScene):",
            "    def construct(self):",
            f"        packed = np.load({asset!r}, allow_pickle=False)",
            '        xs = packed["x"]',
            '        square = packed["square"]',
            '        partials = packed["partials"]',
            "        tracker = ValueTracker(0)",
            "        axes = Axes(x_range=[-3.5, 3.5, 1], y_range=[-1.6, 1.6, 0.5], x_length=10, y_length=4.6, tips=False)",
            _title_line(ir),
            "        def polyline(ys, color):",
            "            pieces = []",
            "            previous = None",
            "            for index in range(len(xs)):",
            "                point = axes.c2p(float(xs[index]), float(ys[index]))",
            "                if previous is not None:",
            "                    pieces.append(Line(previous, point, color=color))",
            "                previous = point",
            "            return VGroup(*pieces)",
            "        square_graph = polyline(square, GRAY)",
            "        def redraw_partial():",
            "            index = int(tracker.get_value())",
            "            last = len(partials) - 1",
            "            if index < 0:",
            "                index = 0",
            "            if index > last:",
            "                index = last",
            "            return polyline(partials[index], BLUE)",
            "        partial = always_redraw(redraw_partial)",
            "        self.add(title, axes, square_graph, partial)",
            "        self.play(tracker.animate.set_value(len(partials) - 1), run_time=8.0, rate_func=linear)",
            "        self.play(self.camera.frame.animate.scale(0.32).move_to(axes.c2p(0.45, 1.12)), run_time=2.2)",
            "        self.wait(1.2)",
            "",
        ]
    )


def _compile_pid(ir: AnimationIR, asset: str) -> str:
    return "\n".join(
        [
            "import numpy as np",
            "from manim import Scene, Text, Axes, Line, VGroup, DashedLine, ValueTracker, always_redraw, UP, YELLOW, BLUE, GREEN, ORANGE, GRAY, linear",
            "",
            "class GeneratedScene(Scene):",
            "    def construct(self):",
            f"        packed = np.load({asset!r}, allow_pickle=False)",
            '        ts = packed["t"]',
            '        ys = packed["y"]',
            "        t_lo = float(ts[0])",
            "        t_hi = float(ts[len(ts) - 1])",
            "        axes = Axes(x_range=[t_lo, t_hi, 2], y_range=[-0.2, 1.8, 0.5], x_length=10, y_length=4.6, tips=False)",
            _title_line(ir),
            "        tracker = ValueTracker(2)",
            "        ref = DashedLine(axes.c2p(t_lo, 1.0), axes.c2p(t_hi, 1.0), color=GRAY)",
            "        def redraw_curve(which, color):",
            "            def redraw():",
            "                last = int(tracker.get_value())",
            "                if last < 2:",
            "                    last = 2",
            "                if last > len(ts) - 1:",
            "                    last = len(ts) - 1",
            "                pieces = []",
            "                previous = None",
            "                for index in range(last):",
            "                    point = axes.c2p(float(ts[index]), float(ys[which][index]))",
            "                    if previous is not None:",
            "                        pieces.append(Line(previous, point, color=color))",
            "                    previous = point",
            "                return VGroup(*pieces)",
            "            return always_redraw(redraw)",
            "        curve_a = redraw_curve(0, BLUE)",
            "        curve_b = redraw_curve(1, GREEN)",
            "        curve_c = redraw_curve(2, ORANGE)",
            "        self.add(title, axes, ref, curve_a, curve_b, curve_c)",
            "        self.play(tracker.animate.set_value(len(ts) - 1), run_time=8.0, rate_func=linear)",
            "",
        ]
    )


def _compile_lorenz(ir: AnimationIR, asset: str) -> str:
    return "\n".join(
        [
            "import numpy as np",
            "from manim import ThreeDScene, Text, ThreeDAxes, Line, VGroup, Dot, ValueTracker, always_redraw, UP, YELLOW, BLUE, RED, GREEN, linear",
            "",
            "class GeneratedScene(ThreeDScene):",
            "    def construct(self):",
            "        self.set_camera_orientation(phi=70 * 3.14159265 / 180, theta=45 * 3.14159265 / 180)",
            f"        packed = np.load({asset!r}, allow_pickle=False)",
            '        paths = packed["paths"]',
            "        tracker = ValueTracker(1)",
            "        axes = ThreeDAxes(x_range=[-24, 24, 8], y_range=[-24, 24, 8], z_range=[0, 48, 8], x_length=6, y_length=6, z_length=4)",
            _title_line(ir),
            "        self.add_fixed_in_frame_mobjects(title)",
            "        colors = [BLUE, RED, GREEN]",
            "        def scaled(point):",
            "            return [float(point[0]) * 0.12, float(point[1]) * 0.12, float(point[2]) * 0.12 - 1.5]",
            "        def trace_path(which, color):",
            "            def redraw_trace():",
            "                last = int(tracker.get_value())",
            "                if last < 1:",
            "                    last = 1",
            "                pieces = []",
            "                previous = None",
            "                for index in range(last):",
            "                    point = scaled(paths[which][index])",
            "                    if previous is not None:",
            "                        pieces.append(Line(previous, point, color=color))",
            "                    previous = point",
            "                group = VGroup(*pieces)",
            "                group.add(Dot(point=previous, color=color, radius=0.06))",
            "                return group",
            "            return always_redraw(redraw_trace)",
            "        traces = VGroup(trace_path(0, BLUE), trace_path(1, RED), trace_path(2, GREEN))",
            "        self.add(title, axes, traces)",
            "        self.begin_ambient_camera_rotation(rate=0.08)",
            "        self.play(tracker.animate.set_value(len(paths[0]) - 1), run_time=12.0, rate_func=linear)",
            "        self.stop_ambient_camera_rotation()",
            "",
        ]
    )


def _compile_csv(ir: AnimationIR, asset: str) -> str:
    return "\n".join(
        [
            "import numpy as np",
            "from manim import Scene, Text, Axes, Line, VGroup, Rectangle, FadeIn, UP, YELLOW, RED, BLUE",
            "",
            "class GeneratedScene(Scene):",
            "    def construct(self):",
            f"        packed = np.load({asset!r}, allow_pickle=False)",
            '        ts = packed["t"]',
            '        temperature = packed["temperature"]',
            '        pressure = packed["pressure"]',
            '        mask = packed["mask"]',
            "        t_min = float(ts[0])",
            "        t_max = float(ts[len(ts) - 1])",
            "        temp_lo = float(min(temperature))",
            "        pressure_lo = float(min(pressure))",
            "        if pressure_lo < 0.001:",
            "            pressure_lo = 1.0",
            "        p_scale = temp_lo / pressure_lo",
            "        pressure_plot = pressure * p_scale",
            "        y_lo = min(temp_lo, float(min(pressure_plot))) - 2.0",
            "        y_hi = max(float(max(temperature)), float(max(pressure_plot))) + 2.0",
            "        axes = Axes(x_range=[t_min, t_max, 50], y_range=[y_lo, y_hi, 5], x_length=10, y_length=4.4, tips=False)",
            "        axes.add_coordinates()",
            _title_line(ir),
            "        def polyline(values, color):",
            "            pieces = []",
            "            previous = None",
            "            for index in range(len(ts)):",
            "                point = axes.c2p(float(ts[index]), float(values[index]))",
            "                if previous is not None:",
            "                    pieces.append(Line(previous, point, color=color))",
            "                previous = point",
            "            return VGroup(*pieces)",
            "        temp_graph = polyline(temperature, RED)",
            "        pressure_graph = polyline(pressure_plot, BLUE)",
            "        left_t = float(ts[0])",
            "        right_t = float(ts[0])",
            "        for index in range(len(mask)):",
            "            if int(mask[index]) == 1:",
            "                left_t = float(ts[index])",
            "                break",
            "        for index in range(len(mask)):",
            "            last = len(mask) - 1 - index",
            "            if int(mask[last]) == 1:",
            "                right_t = float(ts[last])",
            "                break",
            "        mid_y = (y_lo + y_hi) / 2.0",
            "        left_point = axes.c2p(left_t, mid_y)",
            "        right_point = axes.c2p(right_t, mid_y)",
            "        width = float(right_point[0]) - float(left_point[0])",
            "        if width < 0.25:",
            "            width = 0.25",
            "        band = Rectangle(width=width, height=4.2, color=YELLOW)",
            "        band.move_to(axes.c2p((left_t + right_t) / 2.0, mid_y))",
            "        band.set_stroke(YELLOW)",
            "        band.set_fill(YELLOW, opacity=0.2)",
            "        self.add(title, axes, temp_graph, pressure_graph)",
            "        self.wait(1.0)",
            "        self.play(FadeIn(band), run_time=1.2)",
            "        self.wait(2.0)",
            "",
        ]
    )


def _compile_frenet(ir: AnimationIR, asset: str) -> str:
    return "\n".join(
        [
            "import numpy as np",
            "from manim import ThreeDScene, Text, Line, VGroup, Arrow, ValueTracker, always_redraw, UP, YELLOW, RED, GREEN, BLUE, WHITE, linear",
            "",
            "class GeneratedScene(ThreeDScene):",
            "    def construct(self):",
            "        self.set_camera_orientation(phi=65 * 3.14159265 / 180, theta=40 * 3.14159265 / 180)",
            f"        packed = np.load({asset!r}, allow_pickle=False)",
            '        curve = packed["curve"]',
            '        tangent = packed["tangent"]',
            '        normal = packed["normal"]',
            '        binormal = packed["binormal"]',
            "        tracker = ValueTracker(0)",
            _title_line(ir),
            "        self.add_fixed_in_frame_mobjects(title)",
            "        def scaled(point):",
            "            return [float(point[0]), float(point[1]), float(point[2]) * 0.35]",
            "        pieces = []",
            "        previous = None",
            "        for index in range(len(curve)):",
            "            point = scaled(curve[index])",
            "            if previous is not None:",
            "                pieces.append(Line(previous, point, color=WHITE))",
            "            previous = point",
            "        helix = VGroup(*pieces)",
            "        def redraw_frame():",
            "            index = int(tracker.get_value())",
            "            last = len(curve) - 1",
            "            if index < 0:",
            "                index = 0",
            "            if index > last:",
            "                index = last",
            "            origin = scaled(curve[index])",
            "            t_end = [origin[0] + float(tangent[index][0]), origin[1] + float(tangent[index][1]), origin[2] + float(tangent[index][2])]",
            "            n_end = [origin[0] + float(normal[index][0]), origin[1] + float(normal[index][1]), origin[2] + float(normal[index][2])]",
            "            b_end = [origin[0] + float(binormal[index][0]), origin[1] + float(binormal[index][1]), origin[2] + float(binormal[index][2])]",
            "            return VGroup(Arrow(origin, t_end, color=RED, buff=0), Arrow(origin, n_end, color=GREEN, buff=0), Arrow(origin, b_end, color=BLUE, buff=0))",
            "        frame = always_redraw(redraw_frame)",
            "        self.add(title, helix, frame)",
            "        self.play(tracker.animate.set_value(len(curve) - 1), run_time=10.0, rate_func=linear)",
            "",
        ]
    )
