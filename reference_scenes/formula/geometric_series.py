"""A short, deterministic derivation of a finite geometric-series sum."""

from manim import DOWN, UP, MathTex, Scene, Text, Transform, Write


class GeometricSeriesSum(Scene):
    """Derive the finite sum formula by subtracting a shifted series."""

    def construct(self) -> None:
        title = Text("Sum a geometric series", font_size=36).to_edge(UP)
        steps = [
            r"S_n=a+ar+\cdots+ar^{n-1}",
            r"rS_n=ar+\cdots+ar^{n-1}+ar^n",
            r"S_n-rS_n=a-ar^n",
            r"(1-r)S_n=a(1-r^n)",
            r"S_n=\frac{a(1-r^n)}{1-r},\qquad r\ne1",
        ]
        equation = MathTex(steps[0], font_size=58)

        self.play(Write(title), Write(equation), run_time=0.75)
        for step in steps[1:]:
            self.play(Transform(equation, MathTex(step, font_size=58)), run_time=0.8)
        note = Text("Subtract the shifted series", font_size=28).next_to(equation, DOWN, buff=0.7)
        self.play(Write(note), run_time=0.55)
        self.wait(0.4)
