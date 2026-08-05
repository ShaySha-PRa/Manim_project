"""A deterministic ManimCE scene for y = a(x-h)^2 + k parameter changes."""

from manim import (
    BLUE,
    DOWN,
    RED,
    UP,
    WHITE,
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


class ParabolaParameterChangesScene(Scene):
    def construct(self) -> None:
        formula = MathTex(r"y=a(x-h)^2+k").scale(0.95).to_edge(UP)
        axes = Axes(
            x_range=[-4.2, 4.2, 1],
            y_range=[-5, 5, 1],
            x_length=8.6,
            y_length=4.8,
            tips=False,
        ).add_coordinates()
        axis_labels = axes.get_axis_labels(MathTex("x"), MathTex("y"))
        a = ValueTracker(1.0)
        h = ValueTracker(0.0)
        k = ValueTracker(0.0)

        def graph_curve():
            def parabola(x):
                return a.get_value() * (x - h.get_value()) ** 2 + k.get_value()

            return axes.plot(
                parabola,
                x_range=[h.get_value() - 2.0, h.get_value() + 2.0],
                color=BLUE,
            )

        def vertex_point():
            return Dot(axes.c2p(h.get_value(), k.get_value()), color=YELLOW)

        def symmetry_line():
            return DashedLine(
                axes.c2p(h.get_value(), -4.7),
                axes.c2p(h.get_value(), 4.7),
                color=YELLOW,
            )

        def parameter_readout():
            return (
                VGroup(
                    MathTex("a="),
                    DecimalNumber(a.get_value(), num_decimal_places=1, color=RED),
                    MathTex(r"\quad h="),
                    DecimalNumber(h.get_value(), num_decimal_places=1, color=YELLOW),
                    MathTex(r"\quad k="),
                    DecimalNumber(k.get_value(), num_decimal_places=1, color=WHITE),
                )
                .arrange(buff=0.06)
                .scale(0.72)
                .to_edge(DOWN)
            )

        graph = always_redraw(graph_curve)
        vertex = always_redraw(vertex_point)
        symmetry_axis = always_redraw(symmetry_line)
        readout = always_redraw(parameter_readout)

        self.play(Write(formula), run_time=0.5)
        self.play(Create(axes), Write(axis_labels), run_time=0.8)
        self.play(
            Create(graph),
            Create(symmetry_axis),
            FadeIn(vertex),
            FadeIn(readout),
            run_time=0.8,
        )
        self.play(h.animate.set_value(1.0), run_time=1.1)
        self.play(k.animate.set_value(1.2), run_time=1.1)
        self.play(a.animate.set_value(-0.8), run_time=1.2)
        self.wait(0.7)
