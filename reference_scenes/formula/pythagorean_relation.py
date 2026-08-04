"""A short, deterministic algebraic Pythagorean-theorem derivation."""

from manim import DOWN, UP, MathTex, Scene, Text, Transform, Write


class PythagoreanAlgebraicDerivation(Scene):
    """Compare areas in a square made from four congruent right triangles."""

    def construct(self) -> None:
        title = Text("Derive the Pythagorean relation", font_size=36).to_edge(UP)
        steps = [
            r"(a+b)^2=4\left(\frac{ab}{2}\right)+c^2",
            r"a^2+2ab+b^2=2ab+c^2",
            r"a^2+b^2=c^2",
            r"\boxed{c^2=a^2+b^2}",
        ]
        equation = MathTex(steps[0], font_size=62)

        self.play(Write(title), Write(equation), run_time=0.75)
        for step in steps[1:]:
            self.play(Transform(equation, MathTex(step, font_size=62)), run_time=0.8)
        note = Text("Large square area = four triangles + center square", font_size=27).next_to(
            equation, DOWN, buff=0.7
        )
        self.play(Write(note), run_time=0.55)
        self.wait(0.5)
