"""A short, deterministic difference-quotient derivative derivation."""

from manim import BLUE, DOWN, UP, YELLOW, Indicate, MathTex, Scene, Text, Transform, Write


class DifferenceQuotientDerivative(Scene):
    """Use the difference quotient to differentiate x squared."""

    def construct(self) -> None:
        title = Text("Differentiate with a difference quotient", font_size=34, color=BLUE).to_edge(
            UP
        )
        steps = [
            r"f(x)=x^2",
            r"f'(x)=\lim_{h\to0}\frac{(x+h)^2-x^2}{h}",
            r"=\lim_{h\to0}\frac{x^2+2xh+h^2-x^2}{h}",
            r"=\lim_{h\to0}(2x+h)",
            r"f'(x)=2x",
        ]
        reasons = [
            "Choose the function",
            "Apply the difference quotient",
            "Expand the square",
            "Cancel h before the limit",
            "Evaluate the limit",
        ]
        equation = MathTex(steps[0], font_size=56)
        reason = Text(reasons[0], font_size=27, color=YELLOW).next_to(equation, DOWN, buff=0.7)

        self.play(Write(title), run_time=0.45)
        self.play(Write(equation), Write(reason), run_time=0.65)
        for step, explanation in zip(steps[1:], reasons[1:], strict=True):
            next_equation = MathTex(step, font_size=56)
            next_reason = Text(explanation, font_size=27, color=YELLOW).next_to(
                next_equation, DOWN, buff=0.7
            )
            self.play(
                Transform(equation, next_equation), Transform(reason, next_reason), run_time=0.8
            )
            self.play(Indicate(equation, color=YELLOW), run_time=0.3)
        self.wait(0.4)
