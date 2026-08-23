from manim import UP, WHITE, YELLOW, Circle, Create, FadeIn, Polygon, Scene, Text, VGroup


class TriangleCongruenceScene(Scene):
    """Reference geometry scene aligned with the plane-geometry IR compiler."""

    def construct(self) -> None:
        title = Text("全等三角形", font="Noto Sans CJK SC", font_size=36, color=YELLOW).to_edge(UP)
        triangle = Polygon([-2, -1, 0], [2, -1, 0], [0, 2, 0], color=WHITE)
        mark = Circle(radius=0.15, color=YELLOW).move_to([0, -1, 0])
        figure = VGroup(triangle, mark)
        self.play(FadeIn(title), run_time=0.8)
        self.play(Create(figure), run_time=1.5)
        self.wait(0.5)
