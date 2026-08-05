"""A deterministic ManimCE scene for the key features of y = x^2."""

from manim import (
    BLUE,
    DOWN,
    UP,
    YELLOW,
    Axes,
    Create,
    DashedLine,
    Dot,
    FadeIn,
    MathTex,
    Scene,
    Write,
)


class QuadraticKeyFeaturesScene(Scene):
    def construct(self) -> None:
        title = MathTex(r"y=x^2\ \text{is symmetric and has a minimum}").scale(0.78).to_edge(UP)
        axes = Axes(
            x_range=[-3.2, 3.2, 1],
            y_range=[-1, 6, 1],
            x_length=8.4,
            y_length=4.8,
            tips=False,
        ).add_coordinates()
        axis_labels = axes.get_axis_labels(MathTex("x"), MathTex("y"))

        def quadratic(x):
            return x**2

        graph = axes.plot(quadratic, x_range=[-2.35, 2.35], color=BLUE)
        graph_label = MathTex(r"y=x^2", color=BLUE).scale(0.8).move_to(axes.c2p(1.7, 3.7))
        symmetry_axis = DashedLine(axes.c2p(0, -0.7), axes.c2p(0, 5.7), color=YELLOW)
        vertex = Dot(axes.c2p(0, 0), color=YELLOW)
        vertex_label = (
            MathTex(r"\text{vertex }(0,0)", color=YELLOW).scale(0.7).next_to(vertex, DOWN)
        )
        minimum = MathTex(r"x^2\geq0\quad\text{for every }x").scale(0.75).to_edge(DOWN)

        self.play(Write(title), run_time=0.6)
        self.play(Create(axes), Write(axis_labels), run_time=0.9)
        self.play(Create(graph), Write(graph_label), run_time=0.8)
        self.play(Create(symmetry_axis), FadeIn(vertex), Write(vertex_label), run_time=0.8)
        self.play(Write(minimum), run_time=0.6)
        self.wait(0.8)
