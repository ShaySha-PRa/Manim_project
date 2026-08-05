"""Phase 2 scenes for 3b1b ManimGL v1.7.2.

API references (fixed release):
- https://github.com/3b1b/manim/blob/v1.7.2/example_scenes.py
- https://github.com/3b1b/manim/blob/v1.7.2/manimlib/mobject/coordinate_systems.py
"""

from manimlib import (
    BLUE,
    DOWN,
    RED,
    RIGHT,
    UP,
    UR,
    YELLOW,
    Axes,
    DashedLine,
    DecimalNumber,
    Dot,
    FadeIn,
    Line,
    Scene,
    ShowCreation,
    Tex,
    Text,
    Transform,
    TransformMatchingTex,
    ValueTracker,
    VGroup,
    Write,
    always_redraw,
)


def benchmark_axes(x_range=(-4, 4, 1), y_range=(-2, 9, 1)):
    return Axes(
        x_range=x_range,
        y_range=y_range,
        width=10,
        height=5.5,
        axis_config={"include_tip": True},
    ).shift(0.35 * DOWN)


class FormulaTransform(Scene):
    """Complete the square and visibly end with both roots."""

    def construct(self):
        title = Text("Complete the square", font_size=34).to_edge(UP)
        steps = [
            Tex(r"x^2+6x+5=0"),
            Tex(r"x^2+6x=-5"),
            Tex(r"x^2+6x+9=4"),
            Tex(r"(x+3)^2=4"),
            Tex(r"x+3=\pm2"),
            Tex(r"x=-1\quad\text{or}\quad x=-5"),
        ]
        equation = steps[0]
        self.play(Write(title), Write(equation))
        for next_step in steps[1:]:
            self.play(TransformMatchingTex(equation, next_step), run_time=0.8)
            equation = next_step
        self.wait(0.5)


class Derivative(Scene):
    """Derive d(x^2)/dx from the h -> 0 difference quotient."""

    def construct(self):
        title = Tex(r"f(x)=x^2").to_edge(UP)
        steps = [
            Tex(r"f'(x)=\lim_{h\to0}{(x+h)^2-x^2\over h}"),
            Tex(r"=\lim_{h\to0}{2xh+h^2\over h}"),
            Tex(r"=\lim_{h\to0}(2x+h)"),
            Tex(r"{d\over dx}x^2=2x"),
        ]
        equation = steps[0]
        self.play(Write(title), Write(equation))
        for next_step in steps[1:]:
            self.play(TransformMatchingTex(equation, next_step), run_time=0.9)
            equation = next_step
        self.wait(0.5)


class FunctionPlot(Scene):
    """Plot y=x^2 with axes, vertex, and its symmetry axis."""

    def construct(self):
        axes = benchmark_axes((-4, 4, 1), (-1, 9, 1))
        graph = axes.get_graph(lambda x: x**2, x_range=(-3, 3), color=BLUE)
        vertex = Dot(axes.c2p(0, 0), color=YELLOW)
        symmetry = DashedLine(axes.c2p(0, -0.5), axes.c2p(0, 8.5), color=RED)
        label = Tex(r"y=x^2\qquad V=(0,0)").to_edge(UP)
        self.play(ShowCreation(axes), Write(label))
        self.play(ShowCreation(graph), FadeIn(vertex), ShowCreation(symmetry))
        self.wait(0.5)


class ParameterSweep(Scene):
    """Sweep a in y=a(x-h)^2+k while keeping the vertex visible."""

    def construct(self):
        axes = benchmark_axes((-4, 4, 1), (-5, 8, 1))
        a = ValueTracker(1.0)
        h, k = 0.75, -1.0
        graph = always_redraw(
            lambda: axes.get_graph(
                lambda x: a.get_value() * (x - h) ** 2 + k,
                x_range=(-2.4, 3.9),
                color=BLUE,
            )
        )
        vertex = Dot(axes.c2p(h, k), color=YELLOW)
        vertex_label = Tex(r"(h,k)").next_to(vertex, DOWN)
        formula = Tex(r"y=a(x-h)^2+k").to_edge(UP)
        a_readout = always_redraw(
            lambda: VGroup(
                Tex("a="), DecimalNumber(a.get_value(), num_decimal_places=2)
            ).arrange(RIGHT).to_corner(UR)
        )
        self.play(ShowCreation(axes), Write(formula))
        self.add(graph, vertex, vertex_label, a_readout)
        self.play(a.animate.set_value(2.0), run_time=1.0)
        self.play(a.animate.set_value(-1.0), run_time=1.0)
        self.play(a.animate.set_value(0.5), run_time=1.0)
        self.wait(0.4)


class Tangent(Scene):
    """Move a point on y=x^3 and update its tangent slope 3a^2."""

    def construct(self):
        axes = benchmark_axes((-3, 3, 1), (-8, 8, 2))
        curve = axes.get_graph(lambda x: x**3, x_range=(-2, 2), color=BLUE)
        a = ValueTracker(-1.4)

        def tangent_line():
            x = a.get_value()
            y = x**3
            slope = 3 * x**2
            half_width = 0.8
            return Line(
                axes.c2p(x - half_width, y - slope * half_width),
                axes.c2p(x + half_width, y + slope * half_width),
                color=YELLOW,
            )

        moving_point = always_redraw(
            lambda: Dot(axes.c2p(a.get_value(), a.get_value() ** 3), color=RED)
        )
        tangent = always_redraw(tangent_line)
        slope_readout = always_redraw(
            lambda: VGroup(
                Tex(r"m=3a^2="),
                DecimalNumber(3 * a.get_value() ** 2, num_decimal_places=2),
            ).arrange(RIGHT).to_corner(UR)
        )
        title = Tex(r"y=x^3").to_edge(UP)
        self.play(ShowCreation(axes), ShowCreation(curve), Write(title))
        self.add(moving_point, tangent, slope_readout)
        self.play(a.animate.set_value(0.0), run_time=1.2)
        self.play(a.animate.set_value(1.4), run_time=1.2)
        self.wait(0.4)


class Area(Scene):
    """Refine Riemann rectangles for integral_0^2 x^2 dx = 8/3."""

    def construct(self):
        axes = benchmark_axes((-0.5, 2.7, 0.5), (-0.5, 4.7, 1))
        graph = axes.get_graph(lambda x: x**2, x_range=(0, 2.2), color=BLUE)
        coarse = axes.get_riemann_rectangles(
            graph,
            x_range=(0, 2),
            dx=0.5,
            input_sample_type="right",
            fill_opacity=0.65,
        )
        medium = axes.get_riemann_rectangles(
            graph,
            x_range=(0, 2),
            dx=0.25,
            input_sample_type="right",
            fill_opacity=0.65,
        )
        fine = axes.get_riemann_rectangles(
            graph,
            x_range=(0, 2),
            dx=0.1,
            input_sample_type="right",
            fill_opacity=0.65,
        )
        title = Tex(r"\int_0^2x^2\,dx").to_edge(UP)
        answer = Tex(r"\int_0^2x^2\,dx={8\over3}").to_edge(UP)
        self.play(ShowCreation(axes), ShowCreation(graph), Write(title))
        self.play(FadeIn(coarse))
        self.play(Transform(coarse, medium), run_time=0.9)
        self.play(Transform(coarse, fine), run_time=0.9)
        self.play(TransformMatchingTex(title, answer))
        self.wait(0.5)
