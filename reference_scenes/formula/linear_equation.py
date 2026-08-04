"""A short, deterministic derivation of a linear equation."""

from manim import DOWN, UP, MathTex, Scene, Text, Transform, Write


class LinearEquationDerivation(Scene):
    """Solve a one-variable linear equation one reversible step at a time."""

    def construct(self) -> None:
        title = Text("Solve a linear equation", font_size=36).to_edge(UP)
        steps = [
            r"3x-5=16",
            r"3x=16+5",
            r"3x=21",
            r"x=7",
        ]
        equation = MathTex(steps[0], font_size=72)

        self.play(Write(title), Write(equation), run_time=0.75)
        for step in steps[1:]:
            self.play(Transform(equation, MathTex(step, font_size=72)), run_time=0.8)
        conclusion = Text("Check: 3(7) - 5 = 16", font_size=30).next_to(equation, DOWN, buff=0.7)
        self.play(Write(conclusion), run_time=0.55)
        self.wait(0.45)
