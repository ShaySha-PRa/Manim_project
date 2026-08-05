"""A short, deterministic derivation of the quadratic formula."""

from manim import BLUE, DOWN, UP, YELLOW, Indicate, MathTex, Scene, Text, Transform, Write


class QuadraticFormulaDerivation(Scene):
    """Complete a general quadratic square to obtain its closed-form roots."""

    def construct(self) -> None:
        title = Text("Derive the quadratic formula", font_size=36, color=BLUE).to_edge(UP)
        steps = [
            r"ax^2+bx+c=0,\qquad a\ne0",
            r"x^2+\frac{b}{a}x+\frac{c}{a}=0",
            r"\left(x+\frac{b}{2a}\right)^2=\frac{b^2-4ac}{4a^2}",
            r"x+\frac{b}{2a}=\pm\frac{\sqrt{b^2-4ac}}{2a}",
            r"x=\frac{-b\pm\sqrt{b^2-4ac}}{2a}",
        ]
        reasons = [
            "Start with a nonzero leading coefficient",
            "Divide every term by a",
            "Complete the square",
            "Take both square roots",
            "Isolate x",
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
                Transform(equation, next_equation), Transform(reason, next_reason), run_time=0.85
            )
            self.play(Indicate(equation, color=YELLOW), run_time=0.3)
        self.wait(0.45)
