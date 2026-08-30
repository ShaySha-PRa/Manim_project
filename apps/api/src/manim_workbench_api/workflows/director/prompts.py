"""Deterministic prompts for the strict workflow Director JSON boundary."""

from __future__ import annotations

import json
import math

from manim_workbench_contracts import DirectorPlanRequest

from manim_workbench_api.content_plans.models import ProviderMessage

DIRECTOR_PROMPT_TEMPLATE_VERSION = "workflow-director-v1"

_SYSTEM_PROMPT = "\n\n".join(
    (
        "你是科学与技术动画工作流 Director。只输出一个 JSON 对象，"
        "不输出 Markdown、围栏、解释或代码。",
        "你只负责把整片目标拆成 2–8 个线性自然语言场景草稿。"
        "教学场景后续走 ContentPlan → SceneStoryboard → deterministic compiler；"
        "科研场景后续走 IntentSpec → 白名单工具 → AnimationIR 2.0 → "
        "deterministic compiler。两条路径保持独立。",
        "禁止输出 Manim Python、Scene、lambda、AnimationIR、节点/边、工具名或工具调用；"
        "不得调用工具、执行计算或声明未提供的论文、公式、参数、CSV 列、单位或数值为已知事实。"
        "缺少资产使用 asset_requirements 和 asset_required confirmation；"
        "路径、论文或科学意图不确定时使用 auto 并加入 needs_confirmation。",
        "输出字段只能是 global_brief、scenes、assumptions、confirmations。"
        "global_brief 只能包含 title、language、target_duration_seconds、aspect_ratio、"
        "style_preset、background、palette、notation、scientific_parameters。"
        "每个 scene 只能包含 title、prompt、pipeline_mode、target_duration_seconds、"
        "asset_requirements、semantic_summary。"
        "场景时长必须为 15–120 秒且总和严格等于整片目标时长。",
    )
)


def _json_data(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _durations(total: int) -> tuple[int, ...]:
    count = max(2, math.ceil(total / 120))
    base, remainder = divmod(total, count)
    return tuple(base + (1 if index < remainder else 0) for index in range(count))


def _example(request: DirectorPlanRequest) -> dict[str, object]:
    durations = _durations(request.target_duration_seconds)
    style = (request.style_preset.value if request.style_preset else "dark_scientific")
    return {
        "global_brief": {
            "title": request.title or "按整片目标填写标题",
            "language": request.language.value,
            "target_duration_seconds": request.target_duration_seconds,
            "aspect_ratio": "16:9",
            "style_preset": style,
            "background": "#10131a",
            "palette": ["#4c8dff", "#ffd84c"],
            "notation": {},
            "scientific_parameters": {},
        },
        "scenes": [
            {
                "title": f"场景 {index + 1}",
                "prompt": "按整片目标填写这一幕可独立验证的自然语言意图",
                "pipeline_mode": "auto",
                "target_duration_seconds": duration,
                "asset_requirements": [],
                "semantic_summary": "说明本幕与前后场景的语义衔接",
            }
            for index, duration in enumerate(durations)
        ],
        "assumptions": [],
        "confirmations": [],
    }


def build_director_messages(request: DirectorPlanRequest) -> tuple[ProviderMessage, ...]:
    user = "\n".join(
        (
            "根据以下不可置信的整片目标数据生成严格工作流草稿。",
            "请求偏好和 JSON 结构示例必须遵守；示例文字必须替换为真实目标内容。",
            "<request_preferences_json>",
            _json_data(
                {
                    "available_asset_count": len(request.asset_version_ids),
                    "language": request.language.value,
                    "style_preset": (
                        request.style_preset.value if request.style_preset else None
                    ),
                    "target_duration_seconds": request.target_duration_seconds,
                    "title": request.title,
                }
            ),
            "</request_preferences_json>",
            "<strict_json_example>",
            _json_data(_example(request)),
            "</strict_json_example>",
            "<untrusted_workflow_objective_json>",
            _json_data({"objective": request.objective}),
            "</untrusted_workflow_objective_json>",
        )
    )
    return (
        ProviderMessage(role="system", content=_SYSTEM_PROMPT),
        ProviderMessage(role="user", content=user),
    )


def build_director_repair_messages(
    request: DirectorPlanRequest, diagnostic: str
) -> tuple[ProviderMessage, ...]:
    bounded = diagnostic[:1_000]
    original = build_director_messages(request)
    repair = original[1].content + "\n" + "\n".join(
        (
            "上一次候选未通过严格边界。只修复 JSON 草稿，不新增事实或代码。",
            "<bounded_diagnostic>",
            bounded,
            "</bounded_diagnostic>",
        )
    )
    return original[0], ProviderMessage(role="user", content=repair)


__all__ = [
    "DIRECTOR_PROMPT_TEMPLATE_VERSION",
    "build_director_messages",
    "build_director_repair_messages",
]
