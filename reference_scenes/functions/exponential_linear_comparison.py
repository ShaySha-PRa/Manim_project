"""A deterministic ManimCE scene comparing y = e^x with its tangent line."""

import math

from manim import (
    BLUE,
    DOWN,
    GREEN,
    RED,
    UP,
    YELLOW,
    Axes,
    Create,
    DashedLine,
    DecimalNumber,
    Dot,
    FadeIn,
    MathTex,
    Scene,
    ValueTracker,
    VGroup,
    Write,
    always_redraw,
)


class ExponentialLinearComparisonScene(Scene):
    def construct(self) -> None:
        title = MathTex(r"e^x\geq 1+x\qquad\text{with equality at }x=0").scale(0.78).to_edge(UP)
        axes = Axes(
            x_range=[-2.5, 2.4, 1],
            y_range=[-1.5, 6.5, 1],
            x_length=8.6,
            y_length=5.0,
            tips=False,
        ).add_coordinates()
        axis_labels = axes.get_axis_labels(MathTex("x"), MathTex("y"))
        exponential = axes.plot(lambda x: math.exp(x), x_range=[-2.2, 1.8], color=BLUE)
        linear = axes.plot(lambda x: 1 + x, x_range=[-2.4, 2.4], color=GREEN)
        exponential_label = MathTex(r"y=e^x", color=BLUE).scale(0.72).move_to(axes.c2p(1.25, 4.2))
        linear_label = MathTex(r"y=1+x", color=GREEN).scale(0.72).move_to(axes.c2p(-1.65, -0.5))
        tracker = ValueTracker(-1.4)
        point = always_redraw(
            lambda: Dot(axes.c2p(tracker.get_value(), math.exp(tracker.get_value())), color=RED)
        )
        gap = always_redraw(
            lambda: DashedLine(
                axes.c2p(tracker.get_value(), 1 + tracker.get_value()),
                axes.c2p(tracker.get_value(), math.exp(tracker.get_value())),
                color=YELLOW,
            )
        )
        readout = always_redraw(
            lambda: VGroup(
                MathTex("x="),
                DecimalNumber(tracker.get_value(), num_decimal_places=1, color=RED),
                MathTex(r"\qquad e^x-(1+x)="),
                DecimalNumber(
                    math.exp(tracker.get_value()) - 1 - tracker.get_value(),
                    num_decimal_places=2,
                    color=YELLOW,
                ),
            )
            .arrange(buff=0.06)
            .scale(0.68)
            .to_edge(DOWN)
        )
        tangent_point = Dot(axes.c2p(0, 1), color=YELLOW)

        self.play(Write(title), run_time=0.6)
        self.play(Create(axes), Write(axis_labels), run_time=0.8)
        self.play(
            Create(exponential),
            Create(linear),
            Write(exponential_label),
            Write(linear_label),
            run_time=0.9,
        )
        self.play(FadeIn(point), Create(gap), FadeIn(readout), FadeIn(tangent_point), run_time=0.7)
        self.play(tracker.animate.set_value(0.0), run_time=1.1)
        self.play(tracker.animate.set_value(1.4), run_time=1.1)
        self.wait(0.7)
