"""Pure semantic validation for untrusted ContentPlan model responses."""

from __future__ import annotations

import re

from manim_workbench_contracts import (
    ContentPlanGenerationRequest,
    ContentPlanModelResponse,
    ContentPlanOutcome,
    DerivationStyle,
)

from manim_workbench_api.content_plans.errors import ContentPlanSemanticError

_UNSUPPORTED_SCOPE = re.compile(
    r"几何证明|几何.*证明|线性代数|语音|用户素材|用户.*(?:上传|图片|音频|视频)|"
    r"任意.*(?:代码|python).*编辑|geometric?\s+proof|linear\s+algebra|voice|"
    r"user\s+(?:asset|material)|arbitrary\s+(?:code|python).*edit",
    re.IGNORECASE,
)
_DERIVATION_PROMPT = re.compile(r"推导|求导过程|derive|derivation", re.IGNORECASE)
_FUNCTION_VISUALIZATION_PROMPT = re.compile(
    r"图像|函数图|可视化|绘制|绘图|graph|plot|visuali[sz]", re.IGNORECASE
)
_HTML_TAG = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
_SHELL_DIRECTIVE = re.compile(
    r"(?:^|\s)(?:rm\s+-|curl\s+|wget\s+|sudo\s+|bash\s+-|sh\s+-|"
    r"powershell\s+-|cmd(?:\.exe)?\s+/)",
    re.IGNORECASE,
)
_COORDINATE_INTENT = re.compile(
    r"坐标|曲线|函数图|coordinate|axes|axis|curve|graph", re.IGNORECASE
)
_DOMAIN_INTENT = re.compile(
    r"定义域|区间|domain|interval|x\s*(?:∈|属于|in|\\in)|\[[^\]]+\]",
    re.IGNORECASE,
)
_BEHAVIOR_INTENT = re.compile(
    r"关键行为|行为|单调|递增|递减|极值|最大|最小|零点|根|渐近|开口|斜率|"
    r"面积|累计|累积|变化率|"
    r"behavior|monotonic|increas|decreas|extrem|maximum|minimum|zero|root|"
    r"asymptote|concav|slope|area|accumul|rate",
    re.IGNORECASE,
)
_CRITICAL_AMBIGUITY = re.compile(
    r"受众|年级|时长|持续时间|推导风格|证明风格|数学意图|教学目标|"
    r"audience|grade|duration|derivation\s+style|proof\s+style|"
    r"mathematical\s+intent|teaching\s+goal",
    re.IGNORECASE,
)
_AUDIENCE_ASSUMPTION = re.compile(r"受众|audience|学习者|学生|年级", re.IGNORECASE)
_REVERSIBLE_ASSUMPTION = re.compile(
    r"可撤销|可调整|可修改|可更改|可变更|revisable|adjustable|can\s+be\s+changed",
    re.IGNORECASE,
)


def validate_content_plan_response(
    response: ContentPlanModelResponse,
    request: ContentPlanGenerationRequest,
    source_prompt: str,
) -> ContentPlanModelResponse:
    """Return a semantically safe response or raise a field-actionable error.

    Pydantic has already checked the response shape.  This boundary enforces
    constraints whose validity depends on the request, source prompt, or the
    combined teaching plan.
    """
    if _UNSUPPORTED_SCOPE.search(source_prompt):
        if response.outcome is not ContentPlanOutcome.UNSUPPORTED:
            raise ContentPlanSemanticError("unsupported scope must return unsupported")
        return response

    if response.outcome is not ContentPlanOutcome.READY:
        return response

    plan = response.plan
    if plan is None:  # Defensive: the shared schema normally makes this unreachable.
        raise ContentPlanSemanticError("ready response must include plan")

    _validate_request_preservation(plan, request)
    _validate_scenes(plan.scenes)

    if any(_CRITICAL_AMBIGUITY.search(ambiguity) for ambiguity in plan.ambiguities):
        raise ContentPlanSemanticError("critical ambiguities must be resolved before ready")
    if request.audience is None and not any(
        _AUDIENCE_ASSUMPTION.search(assumption) and _REVERSIBLE_ASSUMPTION.search(assumption)
        for assumption in plan.explicit_assumptions
    ):
        raise ContentPlanSemanticError("audience must be clarified or recorded as an assumption")

    for scene in plan.scenes:
        for formula_step in scene.formula_steps:
            _validate_formula(formula_step.expression)

    if _DERIVATION_PROMPT.search(source_prompt):
        formula_step_count = sum(len(scene.formula_steps) for scene in plan.scenes)
        if formula_step_count < 2:
            raise ContentPlanSemanticError("derivation requires at least two formula steps")

    if (
        request.derivation_style is DerivationStyle.VISUAL_INTUITION
        or _FUNCTION_VISUALIZATION_PROMPT.search(source_prompt)
    ):
        _validate_function_visualization(plan.scenes)

    return response


def _validate_request_preservation(plan: object, request: ContentPlanGenerationRequest) -> None:
    if request.audience is not None and plan.audience is not request.audience:
        raise ContentPlanSemanticError("audience must preserve the explicit request")
    if plan.language is not request.language:
        raise ContentPlanSemanticError("language must preserve the explicit request")
    if (
        request.target_duration_seconds is not None
        and plan.target_duration_seconds != request.target_duration_seconds
    ):
        raise ContentPlanSemanticError("target_duration_seconds must preserve the explicit request")
    if (
        request.derivation_style is not None
        and plan.derivation_style is not request.derivation_style
    ):
        raise ContentPlanSemanticError("derivation_style must preserve the explicit request")
    if not set(request.explicit_assumptions).issubset(plan.explicit_assumptions):
        raise ContentPlanSemanticError(
            "explicit_assumptions must preserve every explicit request assumption"
        )


def _validate_scenes(scenes: tuple[object, ...]) -> None:
    for expected_number, scene in enumerate(scenes, start=1):
        if scene.scene_number != expected_number:
            raise ContentPlanSemanticError("scene_number must start at 1 and be contiguous")


def _validate_formula(expression: str) -> None:
    if "```" in expression or _HTML_TAG.search(expression) or _SHELL_DIRECTIVE.search(expression):
        raise ContentPlanSemanticError("formula contains prohibited code or command text")
    if not _is_balanced(expression):
        raise ContentPlanSemanticError("formula has unbalanced brackets")
    if expression.count(r"\left") != expression.count(r"\right"):
        raise ContentPlanSemanticError("formula has unbalanced LaTex left/right delimiters")
    if expression.count(r"\begin{") != expression.count(r"\end{"):
        raise ContentPlanSemanticError("formula has unbalanced LaTex environments")


def _is_balanced(text: str) -> bool:
    opening = {"(", "[", "{"}
    matching_open = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    for character in text:
        if character in opening:
            stack.append(character)
        elif character in matching_open:
            if not stack or stack.pop() != matching_open[character]:
                return False
    return not stack


def _validate_function_visualization(scenes: tuple[object, ...]) -> None:
    plan_text_parts: list[str] = []
    for scene in scenes:
        plan_text_parts.extend(
            (scene.teaching_goal, scene.visual_intent, scene.narration_placeholder)
        )
        for step in scene.formula_steps:
            plan_text_parts.extend((step.expression, step.explanation))
    plan_text = " ".join(plan_text_parts)
    if not (
        _COORDINATE_INTENT.search(plan_text)
        and _DOMAIN_INTENT.search(plan_text)
        and _BEHAVIOR_INTENT.search(plan_text)
    ):
        raise ContentPlanSemanticError(
            "function_visualization requires coordinate, domain, and key behavior intent"
        )
