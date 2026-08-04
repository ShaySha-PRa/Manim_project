"""A deterministic ManimCE scene for transformations of a sine curve."""

import math

from manim import (
    BLUE,
    DOWN,
    GRAY_B,
    PI,
    RED,
    UP,
    WHITE,
    YELLOW,
    Axes,
    Create,
    DecimalNumber,
    FadeIn,
    MathTex,
    Scene,
    ValueTracker,
    VGroup,
    Write,
    always_redraw,
)


class SineParameterTransformationsScene(Scene):
    def construct(self) -> None:
        title = MathTex(r"y=A\sin(\omega x+\varphi)+D").scale(0.9).to_edge(UP)
        axes = Axes(
            x_range=[-2 * PI, 2 * PI, PI / 2],
            y_range=[-3.5, 3.5, 1],
            x_length=9.2,
            y_length=4.6,
            tips=False,
        )
        axis_labels = axes.get_axis_labels(MathTex("x"), MathTex("y"))
        baseline = axes.plot(lambda x: math.sin(x), x_range=[-2 * PI, 2 * PI], color=GRAY_B)
        amplitude = ValueTracker(1.0)
        frequency = ValueTracker(1.0)
        phase = ValueTracker(0.0)
        vertical_shift = ValueTracker(0.0)
        transformed = always_redraw(
            lambda: axes.plot(
                lambda x: amplitude.get_value()
                * math.sin(frequency.get_value() * x + phase.get_value())
                + vertical_shift.get_value(),
                x_range=[-2 * PI, 2 * PI],
                color=BLUE,
            )
        )
        readout = always_redraw(
            lambda: VGroup(
                MathTex("A="),
                DecimalNumber(amplitude.get_value(), num_decimal_places=1, color=RED),
                MathTex(r"\quad\omega="),
                DecimalNumber(frequency.get_value(), num_decimal_places=1, color=YELLOW),
                MathTex(r"\quad\varphi="),
                DecimalNumber(phase.get_value(), num_decimal_places=1, color=WHITE),
                MathTex(r"\quad D="),
                DecimalNumber(vertical_shift.get_value(), num_decimal_places=1, color=WHITE),
            )
            .arrange(buff=0.05)
            .scale(0.62)
            .to_edge(DOWN)
        )
        baseline_label = (
            MathTex(r"y=\sin x", color=GRAY_B).scale(0.65).move_to(axes.c2p(-4.8, -2.7))
        )

        self.play(Write(title), run_time=0.5)
        self.play(Create(axes), Write(axis_labels), run_time=0.8)
        self.play(
            Create(baseline),
            Create(transformed),
            FadeIn(readout),
            Write(baseline_label),
            run_time=0.8,
        )
        self.play(amplitude.animate.set_value(1.8), run_time=0.9)
        self.play(frequency.animate.set_value(0.7), run_time=0.9)
        self.play(phase.animate.set_value(-0.7), run_time=0.9)
        self.play(vertical_shift.animate.set_value(0.6), run_time=0.9)
        self.wait(0.7)
