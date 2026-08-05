"""A deterministic ManimCE scene for the moving tangent of y = x^3."""

from manim import (
    BLUE,
    DOWN,
    RED,
    UP,
    YELLOW,
    Axes,
    Create,
    DecimalNumber,
    Dot,
    FadeIn,
    Line,
    MathTex,
    Scene,
    ValueTracker,
    VGroup,
    Write,
    always_redraw,
)


class CubicMovingTangentScene(Scene):
    def construct(self) -> None:
        title = MathTex(r"f(x)=x^3,\qquad f'(a)=3a^2").scale(0.85).to_edge(UP)
        axes = Axes(
            x_range=[-2.5, 2.5, 1],
            y_range=[-6, 6, 2],
            x_length=8.4,
            y_length=4.8,
            tips=False,
        ).add_coordinates()

        def cubic(x):
            return x**3

        graph = axes.plot(cubic, x_range=[-1.8, 1.8], color=BLUE)
        graph_label = MathTex(r"y=x^3", color=BLUE).scale(0.75).move_to(axes.c2p(-1.45, -4.7))
        parameter = ValueTracker(-1.2)

        def moving_point():
            return Dot(
                axes.c2p(parameter.get_value(), parameter.get_value() ** 3),
                color=RED,
            )

        point = always_redraw(moving_point)

        def tangent_line() -> Line:
            x_value = parameter.get_value()
            slope = 3 * x_value**2
            return Line(
                axes.c2p(x_value - 0.62, x_value**3 - 0.62 * slope),
                axes.c2p(x_value + 0.62, x_value**3 + 0.62 * slope),
                color=YELLOW,
            )

        tangent = always_redraw(tangent_line)

        def parameter_readout():
            return (
                VGroup(
                    MathTex("a="),
                    DecimalNumber(parameter.get_value(), num_decimal_places=1, color=RED),
                    MathTex(r"\qquad m=3a^2="),
                    DecimalNumber(
                        3 * parameter.get_value() ** 2, num_decimal_places=2, color=YELLOW
                    ),
                )
                .arrange(buff=0.06)
                .scale(0.72)
                .to_edge(DOWN)
            )

        readout = always_redraw(parameter_readout)

        self.play(Write(title), run_time=0.6)
        self.play(Create(axes), Create(graph), Write(graph_label), run_time=0.9)
        self.play(FadeIn(point), Create(tangent), FadeIn(readout), run_time=0.7)
        self.play(parameter.animate.set_value(0.0), run_time=1.2)
        self.play(parameter.animate.set_value(1.2), run_time=1.2)
        self.wait(0.7)
