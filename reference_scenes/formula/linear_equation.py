"""A short, deterministic derivation of a linear equation."""

from manim import BLUE, DOWN, UP, YELLOW, Indicate, MathTex, Scene, Text, Transform, Write


class LinearEquationDerivation(Scene):
    """Solve a one-variable linear equation one reversible step at a time."""

    def construct(self) -> None:
        title = Text("Solve a linear equation", font_size=36, color=BLUE).to_edge(UP)
        steps = [
            r"3x-5=16",
            r"3x=16+5",
            r"3x=21",
            r"x=7",
        ]
        reasons = [
            "Start with the equation",
            "Add 5 to both sides",
            "Simplify",
            "Divide both sides by 3",
        ]
        equation = MathTex(steps[0], font_size=72)
        reason = Text(reasons[0], font_size=27, color=YELLOW).next_to(equation, DOWN, buff=0.7)

        self.play(Write(title), run_time=0.45)
        self.play(Write(equation), Write(reason), run_time=0.65)
        for step, explanation in zip(steps[1:], reasons[1:], strict=True):
            next_equation = MathTex(step, font_size=72)
            next_reason = Text(explanation, font_size=27, color=YELLOW).next_to(
                next_equation, DOWN, buff=0.7
            )
            self.play(
                Transform(equation, next_equation), Transform(reason, next_reason), run_time=0.8
            )
            self.play(Indicate(equation, color=YELLOW), run_time=0.3)
        self.wait(0.45)
