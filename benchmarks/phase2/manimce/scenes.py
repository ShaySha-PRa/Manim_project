"""Six semantic scenes for the Phase 2 Manim Community 0.20.1 benchmark.

APIs used here are documented for Manim Community v0.20.1:
https://docs.manim.community/en/stable/reference/manim.mobject.graphing.coordinate_systems.CoordinateSystem.html
https://docs.manim.community/en/stable/reference/manim.animation.updaters.mobject_update_utils.html
"""

from manim import *


SCENE_IDS: dict[str, type[Scene]] = {}


class FormulaTransform(Scene):
    def construct(self):
        title = Text("Completing the square", font_size=36).to_edge(UP)
        steps = [
            r"x^2+6x+5=0",
            r"x^2+6x=-5",
            r"x^2+6x+9=4",
            r"(x+3)^2=4",
            r"x+3=\pm2",
            r"x=-1\quad\text{or}\quad x=-5",
        ]
        equation = MathTex(steps[0]).scale(1.25)
        self.play(Write(title), Write(equation))
        for step in steps[1:]:
            next_equation = MathTex(step).scale(1.25)
            self.play(Transform(equation, next_equation), run_time=0.7)
        self.wait(0.4)


class Derivative(Scene):
    def construct(self):
        title = Text("Difference quotient", font_size=36).to_edge(UP)
        steps = [
            r"\frac{d}{dx}(x^2)=\lim_{h\to0}\frac{(x+h)^2-x^2}{h}",
            r"=\lim_{h\to0}\frac{x^2+2xh+h^2-x^2}{h}",
            r"=\lim_{h\to0}(2x+h)",
            r"=2x",
        ]
        equation = MathTex(steps[0]).scale(1.08)
        self.play(Write(title), Write(equation))
        for step in steps[1:]:
            next_equation = MathTex(step).scale(1.08)
            self.play(Transform(equation, next_equation), run_time=0.8)
        self.wait(0.4)


class FunctionPlot(Scene):
    def construct(self):
        axes = Axes(
            x_range=[-3, 3, 1], y_range=[-1, 6, 1], x_length=8, y_length=5,
            tips=False,
        ).add_coordinates()
        labels = axes.get_axis_labels(MathTex("x"), MathTex("y"))
        graph = axes.plot(lambda x: x**2, x_range=[-2.35, 2.35], color=BLUE)
        vertex = Dot(axes.c2p(0, 0), color=YELLOW)
        vertex_label = MathTex(r"(0,0)").next_to(vertex, DOWN + RIGHT)
        symmetry = DashedLine(axes.c2p(0, -0.7), axes.c2p(0, 5.8), color=YELLOW)
        graph_label = MathTex(r"y=x^2", color=BLUE).next_to(axes.c2p(1.7, 3.0), UR)
        self.play(Create(axes), Write(labels))
        self.play(Create(graph), Create(symmetry), FadeIn(vertex), Write(vertex_label), Write(graph_label))
        self.wait(0.4)


class ParameterSweep(Scene):
    def construct(self):
        axes = Axes(
            x_range=[-4, 4, 1], y_range=[-2, 6, 1], x_length=8, y_length=5,
            tips=False,
        ).add_coordinates()
        h, k = 1, -1
        a = ValueTracker(0.5)
        vertex = Dot(axes.c2p(h, k), color=YELLOW)
        vertex_label = MathTex(r"(h,k)=(1,-1)", color=YELLOW).next_to(vertex, DOWN)
        graph = always_redraw(
            lambda: axes.plot(lambda x: a.get_value() * (x - h) ** 2 + k, color=BLUE)
        )
        readout = always_redraw(
            lambda: VGroup(
                MathTex(r"y=a(x-1)^2-1,\quad a="),
                DecimalNumber(a.get_value(), num_decimal_places=1, color=RED),
            ).arrange(RIGHT, buff=0.08).to_edge(UP)
        )
        self.play(Create(axes), FadeIn(vertex), Write(vertex_label), Create(graph), FadeIn(readout))
        self.play(a.animate.set_value(2.0), run_time=1.2)
        self.play(a.animate.set_value(-0.8), run_time=1.2)
        self.wait(0.4)


class Tangent(Scene):
    def construct(self):
        axes = Axes(
            x_range=[-2.5, 2.5, 1], y_range=[-6, 6, 2], x_length=8, y_length=5,
            tips=False,
        ).add_coordinates()
        graph = axes.plot(lambda x: x**3, x_range=[-1.8, 1.8], color=BLUE)
        a = ValueTracker(-1.25)

        def tangent_line():
            x0 = a.get_value()
            slope = 3 * x0**2
            left, right = x0 - 0.7, x0 + 0.7
            f = lambda x: x0**3 + slope * (x - x0)
            return Line(axes.c2p(left, f(left)), axes.c2p(right, f(right)), color=YELLOW)

        point = always_redraw(lambda: Dot(axes.c2p(a.get_value(), a.get_value() ** 3), color=RED))
        tangent = always_redraw(tangent_line)
        slope_label = always_redraw(
            lambda: VGroup(
                MathTex(r"m=3a^2="),
                DecimalNumber(3 * a.get_value() ** 2, num_decimal_places=2, color=YELLOW),
            ).arrange(RIGHT, buff=0.08).to_edge(UP)
        )
        self.play(Create(axes), Create(graph), FadeIn(point), Create(tangent), FadeIn(slope_label))
        self.play(a.animate.set_value(1.15), run_time=2.0)
        self.wait(0.4)


class Area(Scene):
    def construct(self):
        axes = Axes(
            x_range=[-0.2, 2.4, 0.5], y_range=[-0.2, 4.5, 1], x_length=7, y_length=5,
            tips=False,
        ).add_coordinates()
        graph = axes.plot(lambda x: x**2, x_range=[0, 2], color=BLUE)
        coarse = axes.get_riemann_rectangles(
            graph, x_range=[0, 2], dx=0.5, input_sample_type="right", stroke_width=1,
        )
        fine = axes.get_riemann_rectangles(
            graph, x_range=[0, 2], dx=0.1, input_sample_type="right", stroke_width=0.5,
        )
        area_label = MathTex(r"\int_0^2 x^2\,dx=\frac{8}{3}").to_edge(UP)
        interval_label = MathTex(r"y=x^2\ \text{on}\ [0,2]", color=BLUE).next_to(axes.c2p(1.2, 3.0), RIGHT)
        self.play(Create(axes), Create(graph), Write(interval_label))
        self.play(Create(coarse), run_time=0.9)
        self.play(Transform(coarse, fine), run_time=1.1)
        self.play(Write(area_label))
        self.wait(0.4)


# The runner resolves contract IDs through this map and invokes each class independently.
SCENE_IDS["formula_transform"] = FormulaTransform
SCENE_IDS["derivative"] = Derivative
SCENE_IDS["function_plot"] = FunctionPlot
SCENE_IDS["parameter_sweep"] = ParameterSweep
SCENE_IDS["tangent"] = Tangent
SCENE_IDS["area"] = Area
