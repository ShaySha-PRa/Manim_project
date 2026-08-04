"""A short, deterministic difference-quotient derivative derivation."""

from manim import DOWN, UP, MathTex, Scene, Text, Transform, Write


class DifferenceQuotientDerivative(Scene):
    """Use the difference quotient to differentiate x squared."""

    def construct(self) -> None:
        title = Text("Differentiate with a difference quotient", font_size=34).to_edge(UP)
        steps = [
            r"f(x)=x^2",
            r"f'(x)=\lim_{h\to0}\frac{(x+h)^2-x^2}{h}",
            r"=\lim_{h\to0}\frac{x^2+2xh+h^2-x^2}{h}",
            r"=\lim_{h\to0}(2x+h)",
            r"f'(x)=2x",
        ]
        equation = MathTex(steps[0], font_size=56)

        self.play(Write(title), Write(equation), run_time=0.75)
        for step in steps[1:]:
            self.play(Transform(equation, MathTex(step, font_size=56)), run_time=0.8)
        note = Text("Cancel h before taking the limit", font_size=28).next_to(
            equation, DOWN, buff=0.7
        )
        self.play(Write(note), run_time=0.55)
        self.wait(0.4)
