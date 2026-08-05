"""A deterministic ManimCE scene for Riemann sums approaching an area."""

from manim import (
    BLUE,
    DOWN,
    UP,
    YELLOW,
    Axes,
    Create,
    MathTex,
    Scene,
    Transform,
    Write,
)


class RiemannSumAreaScene(Scene):
    def construct(self) -> None:
        title = MathTex(r"\int_0^2 x^2\,dx=\frac{8}{3}").scale(0.95).to_edge(UP)
        axes = Axes(
            x_range=[-0.2, 2.4, 0.5],
            y_range=[-0.2, 4.5, 1],
            x_length=7.1,
            y_length=4.8,
            tips=False,
        ).add_coordinates()
        axes.shift(0.25 * UP)
        axis_labels = axes.get_axis_labels(MathTex("x"), MathTex("y"))

        def quadratic(x):
            return x**2

        graph = axes.plot(quadratic, x_range=[0, 2], color=BLUE)
        graph_label = MathTex(r"y=x^2", color=BLUE).scale(0.75).move_to(axes.c2p(1.4, 3.6))
        coarse = axes.get_riemann_rectangles(
            graph,
            x_range=[0, 2],
            dx=0.5,
            input_sample_type="right",
            fill_opacity=0.55,
            stroke_width=1.0,
            color=YELLOW,
        )
        medium = axes.get_riemann_rectangles(
            graph,
            x_range=[0, 2],
            dx=0.25,
            input_sample_type="right",
            fill_opacity=0.55,
            stroke_width=0.7,
            color=YELLOW,
        )
        fine = axes.get_riemann_rectangles(
            graph,
            x_range=[0, 2],
            dx=0.1,
            input_sample_type="right",
            fill_opacity=0.55,
            stroke_width=0.35,
            color=YELLOW,
        )
        limit_label = MathTex(r"\text{right-endpoint sums }\longrightarrow\text{ area}").scale(0.7)
        limit_label.to_edge(UP).shift(0.58 * DOWN)

        self.play(Write(title), run_time=0.6)
        self.play(Create(axes), Write(axis_labels), run_time=0.8)
        self.play(Create(graph), Write(graph_label), run_time=0.7)
        self.play(Create(coarse), run_time=0.7)
        self.play(Transform(coarse, medium), run_time=0.8)
        self.play(Transform(coarse, fine), Write(limit_label), run_time=0.9)
        self.wait(0.7)
