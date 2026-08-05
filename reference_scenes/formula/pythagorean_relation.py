"""A short, deterministic algebraic Pythagorean-theorem derivation."""

from manim import BLUE, DOWN, UP, YELLOW, Indicate, MathTex, Scene, Text, Transform, Write


class PythagoreanAlgebraicDerivation(Scene):
    """Compare areas in a square made from four congruent right triangles."""

    def construct(self) -> None:
        title = Text("Derive the Pythagorean relation", font_size=36, color=BLUE).to_edge(UP)
        steps = [
            r"(a+b)^2=4\left(\frac{ab}{2}\right)+c^2",
            r"a^2+2ab+b^2=2ab+c^2",
            r"a^2+b^2=c^2",
            r"\boxed{c^2=a^2+b^2}",
        ]
        reasons = [
            "Equate the two area descriptions",
            "Expand and combine triangle areas",
            "Cancel the common 2ab term",
            "State the Pythagorean relation",
        ]
        equation = MathTex(steps[0], font_size=62)
        reason = Text(reasons[0], font_size=27, color=YELLOW).next_to(equation, DOWN, buff=0.7)

        self.play(Write(title), run_time=0.45)
        self.play(Write(equation), Write(reason), run_time=0.65)
        for step, explanation in zip(steps[1:], reasons[1:], strict=True):
            next_equation = MathTex(step, font_size=62)
            next_reason = Text(explanation, font_size=27, color=YELLOW).next_to(
                next_equation, DOWN, buff=0.7
            )
            self.play(
                Transform(equation, next_equation), Transform(reason, next_reason), run_time=0.8
            )
            self.play(Indicate(equation, color=YELLOW), run_time=0.3)
        self.wait(0.5)
