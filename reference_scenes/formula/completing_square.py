"""A short, deterministic completing-the-square derivation."""

from manim import DOWN, UP, MathTex, Scene, Text, Transform, Write


class CompletingSquareDerivation(Scene):
    """Derive the two roots of a quadratic by completing its square."""

    def construct(self) -> None:
        title = Text("Complete the square", font_size=36).to_edge(UP)
        steps = [
            r"x^2+6x+5=0",
            r"x^2+6x=-5",
            r"x^2+6x+9=4",
            r"(x+3)^2=4",
            r"x+3=\pm2",
            r"x=-1\quad\text{or}\quad x=-5",
        ]
        equation = MathTex(steps[0], font_size=66)

        self.play(Write(title), Write(equation), run_time=0.75)
        for step in steps[1:]:
            self.play(Transform(equation, MathTex(step, font_size=66)), run_time=0.65)
        note = Text("Add (6 / 2)^2 to both sides", font_size=28).next_to(
            equation, DOWN, buff=0.7
        )
        self.play(Write(note), run_time=0.55)
        self.wait(0.35)
