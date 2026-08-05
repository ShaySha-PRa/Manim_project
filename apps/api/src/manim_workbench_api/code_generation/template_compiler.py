from __future__ import annotations

import ast
import json
import math

from manim_workbench_contracts import (
    CodeGenerationCategory,
    CodeModelResponse,
    ContentPlanVersion,
)


def compile_deterministic_template(
    plan: ContentPlanVersion,
    category: CodeGenerationCategory,
) -> CodeModelResponse:
    lines = [plan.title]
    for scene in plan.scenes[:4]:
        lines.append(scene.teaching_goal)
        lines.extend(step.expression for step in scene.formula_steps[:2])
    lines = [_bounded_text(value) for value in lines[:9]]
    declarations = [
        f"        item_{index} = Text({json.dumps(value, ensure_ascii=False)}, "
        'font_size=30, font="Noto Sans CJK SC")'
        for index, value in enumerate(lines)
    ]
    item_names = ", ".join(f"item_{index}" for index in range(len(lines)))
    reading_seconds = min(1.0, plan.target_duration_seconds * 0.1 / len(lines))
    animation_budget = plan.target_duration_seconds - reading_seconds * len(lines)
    animations_per_item = max(2, math.ceil(animation_budget / (len(lines) * 4.0)))
    animation_seconds = animation_budget / (len(lines) * animations_per_item)
    timeline: list[str] = []
    for index in range(len(lines)):
        timeline.append(f"        self.play(FadeIn(item_{index}), run_time={animation_seconds!r})")
        timeline.extend(
            f"        self.play(Indicate(item_{index}, color=YELLOW), "
            f"run_time={animation_seconds!r})"
            for _ in range(animations_per_item - 1)
        )
        timeline.append(f"        self.wait({reading_seconds!r})")
    source = "\n".join(
        [
            "from manim import DOWN, FadeIn, Indicate, Scene, Text, VGroup, YELLOW",
            "",
            "class GeneratedScene(Scene):",
            "    def construct(self):",
            *declarations,
            f"        content = VGroup({item_names}).arrange(DOWN, buff=0.25)",
            "        content.move_to([0, 0, 0])",
            *timeline,
            "",
        ]
    )
    return CodeModelResponse(
        scene_class="GeneratedScene",
        code=source,
        assumptions=(f"使用 {category.value} 确定性降级模板。",),
    )


def degrade_mathtex_to_text(source: str) -> str:
    """Replace Manim MathTex calls after a confirmed LaTeX runtime failure."""
    try:
        tree = ast.parse(source, mode="exec")
    except (SyntaxError, ValueError, TypeError):
        return source
    manim_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "manim" and node.level == 0
    ]
    math_names = {
        alias.asname or alias.name
        for node in manim_imports
        for alias in node.names
        if alias.name == "MathTex"
    }
    if not math_names:
        return source
    text_names = [
        alias.asname or alias.name
        for node in manim_imports
        for alias in node.names
        if alias.name == "Text"
    ]
    text_name = text_names[0] if text_names else "Text"
    transformer = _MathTexToText(math_names=math_names, text_name=text_name)
    tree = transformer.visit(tree)
    if transformer.replacements == 0:
        return source
    if not text_names:
        manim_imports[0].names.append(ast.alias(name="Text"))
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


class _MathTexToText(ast.NodeTransformer):
    def __init__(self, *, math_names: set[str], text_name: str) -> None:
        self._math_names = math_names
        self._text_name = text_name
        self.replacements = 0

    def visit_Call(self, node: ast.Call) -> ast.AST:  # noqa: N802
        node = self.generic_visit(node)
        if not isinstance(node.func, ast.Name) or node.func.id not in self._math_names:
            return node
        if len(node.args) > 1:
            if not all(
                isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                for argument in node.args
            ):
                return node
            combined = " ".join(str(argument.value) for argument in node.args)
            node.args = [ast.Constant(value=combined)]
        node.func = ast.Name(id=self._text_name, ctx=ast.Load())
        node.keywords = [
            keyword
            for keyword in node.keywords
            if keyword.arg not in {"arg_separator", "substrings_to_isolate", "tex_template"}
        ]
        if not any(keyword.arg == "font" for keyword in node.keywords):
            node.keywords.append(
                ast.keyword(arg="font", value=ast.Constant(value="Noto Sans CJK SC"))
            )
        self.replacements += 1
        return node


def _bounded_text(value: str) -> str:
    collapsed = " ".join(value.split())
    return collapsed[:180] or "Content"
