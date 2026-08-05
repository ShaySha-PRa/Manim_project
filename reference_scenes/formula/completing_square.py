"""A short, deterministic completing-the-square derivation."""

from manim import BLUE, DOWN, UP, YELLOW, Indicate, MathTex, Scene, Text, Transform, Write


class CompletingSquareDerivation(Scene):
    """Derive the two roots of a quadratic by completing its square."""

    def construct(self) -> None:
        title = Text("Complete the square", font_size=36, color=BLUE).to_edge(UP)
        steps = [
            r"x^2+6x+5=0",
            r"x^2+6x=-5",
            r"x^2+6x+9=4",
            r"(x+3)^2=4",
            r"x+3=\pm2",
            r"x=-1\quad\text{or}\quad x=-5",
        ]
        reasons = [
            "Start with the quadratic",
            "Move the constant",
            "Add the same square to both sides",
            "Factor the perfect square",
            "Take both square roots",
            "Isolate x",
        ]
        equation = MathTex(steps[0], font_size=66)
        reason = Text(reasons[0], font_size=27, color=YELLOW).next_to(equation, DOWN, buff=0.7)

        self.play(Write(title), run_time=0.45)
        self.play(Write(equation), Write(reason), run_time=0.65)
        for step, explanation in zip(steps[1:], reasons[1:], strict=True):
            next_equation = MathTex(step, font_size=66)
            next_reason = Text(explanation, font_size=27, color=YELLOW).next_to(
                next_equation, DOWN, buff=0.7
            )
            self.play(
                Transform(equation, next_equation), Transform(reason, next_reason), run_time=0.7
            )
            self.play(Indicate(equation, color=YELLOW), run_time=0.3)
        self.wait(0.35)
