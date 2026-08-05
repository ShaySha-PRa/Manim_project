"""A short, deterministic derivation of a finite geometric-series sum."""

from manim import BLUE, DOWN, UP, YELLOW, Indicate, MathTex, Scene, Text, Transform, Write


class GeometricSeriesSum(Scene):
    """Derive the finite sum formula by subtracting a shifted series."""

    def construct(self) -> None:
        title = Text("Sum a geometric series", font_size=36, color=BLUE).to_edge(UP)
        steps = [
            r"S_n=a+ar+\cdots+ar^{n-1}",
            r"rS_n=ar+\cdots+ar^{n-1}+ar^n",
            r"S_n-rS_n=a-ar^n",
            r"(1-r)S_n=a(1-r^n)",
            r"S_n=\frac{a(1-r^n)}{1-r},\qquad r\ne1",
        ]
        reasons = [
            "Write the finite series",
            "Multiply every term by r",
            "Subtract aligned terms",
            "Factor both sides",
            "Divide by 1-r",
        ]
        equation = MathTex(steps[0], font_size=58)
        reason = Text(reasons[0], font_size=27, color=YELLOW).next_to(equation, DOWN, buff=0.7)

        self.play(Write(title), run_time=0.45)
        self.play(Write(equation), Write(reason), run_time=0.65)
        for step, explanation in zip(steps[1:], reasons[1:], strict=True):
            next_equation = MathTex(step, font_size=58)
            next_reason = Text(explanation, font_size=27, color=YELLOW).next_to(
                next_equation, DOWN, buff=0.7
            )
            self.play(
                Transform(equation, next_equation), Transform(reason, next_reason), run_time=0.8
            )
            self.play(Indicate(equation, color=YELLOW), run_time=0.3)
        self.wait(0.4)
