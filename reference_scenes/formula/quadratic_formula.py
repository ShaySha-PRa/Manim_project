"""A short, deterministic derivation of the quadratic formula."""

from manim import DOWN, UP, MathTex, Scene, Text, Transform, Write


class QuadraticFormulaDerivation(Scene):
    """Complete a general quadratic square to obtain its closed-form roots."""

    def construct(self) -> None:
        title = Text("Derive the quadratic formula", font_size=36).to_edge(UP)
        steps = [
            r"ax^2+bx+c=0,\qquad a\ne0",
            r"x^2+\frac{b}{a}x+\frac{c}{a}=0",
            r"\left(x+\frac{b}{2a}\right)^2=\frac{b^2-4ac}{4a^2}",
            r"x+\frac{b}{2a}=\pm\frac{\sqrt{b^2-4ac}}{2a}",
            r"x=\frac{-b\pm\sqrt{b^2-4ac}}{2a}",
        ]
        equation = MathTex(steps[0], font_size=58)

        self.play(Write(title), Write(equation), run_time=0.75)
        for step in steps[1:]:
            self.play(Transform(equation, MathTex(step, font_size=58)), run_time=0.85)
        note = Text("Divide by a, then complete the square", font_size=28).next_to(
            equation, DOWN, buff=0.65
        )
        self.play(Write(note), run_time=0.55)
        self.wait(0.45)
