"""Resolve one-sentence prompts into IntentSpec. LLM may only fill this JSON."""

from __future__ import annotations

import json
import re

from manim_workbench_contracts import IntentSpec, ToolNeed, ToolOp
from manim_workbench_contracts.intent import IntentDomain
from manim_workbench_contracts.models import CodeGenerationCategory

_WAVE = re.compile(r"波包|干涉|wave.?packet|interfer", re.I)
_FOURIER = re.compile(r"傅里叶|傅立叶|gibbs|方波|fourier", re.I)
_LORENZ = re.compile(r"lorenz|洛伦兹", re.I)
_PID = re.compile(r"\bpid\b|阶跃响应|超调", re.I)
_CSV = re.compile(r"csv|异常|temperature|pressure|时序", re.I)
_FRENET = re.compile(r"frenet|切向量|法向量|副法|螺旋", re.I)


def intent_from_llm_json(payload: str) -> IntentSpec:
    """Parse model output that must be IntentSpec JSON only."""
    text = payload.strip()
    if text.startswith("```"):
        raise ValueError("IntentSpec JSON must not be fenced")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("IntentSpec must be an object")
    return IntentSpec.model_validate(data)


def resolve_intent(prompt: str, *, csv_text: str | None = None) -> IntentSpec:
    text = prompt.strip()
    if _WAVE.search(text):
        return IntentSpec(
            domain=IntentDomain.PHYSICS_WAVE,
            goal="two Gaussian packets collide and interfere",
            assumptions=(
                "二维波动方程线性叠加",
                "波速 c=1.15，波数 k=6.2",
                "两高斯波包沿 x 相向传播，时间窗覆盖对撞并穿过",
            ),
            tools_needed=(ToolNeed(op=ToolOp.WAVE2D_SUPERPOSITION, params={"c": 1.15, "k": 6.2}),),
            output_duration_seconds=9.5,
            dimension="2d",
            category_hint=CodeGenerationCategory.FUNCTION_VISUALIZATION,
        )
    if _FOURIER.search(text):
        return IntentSpec(
            domain=IntentDomain.MATH_SIGNAL,
            goal="show Fourier convergence and Gibbs overshoot",
            assumptions=("周期 2π 的方波", "只使用奇数谐波", "N 增至 31"),
            tools_needed=(ToolNeed(op=ToolOp.FOURIER_SQUARE_WAVE, params={"n_max": 31}),),
            output_duration_seconds=12.0,
            dimension="2d",
            category_hint=CodeGenerationCategory.FUNCTION_VISUALIZATION,
        )
    if _LORENZ.search(text):
        return IntentSpec(
            domain=IntentDomain.DYNAMICAL_SYSTEMS,
            goal="visualize sensitive dependence",
            assumptions=("σ=10, ρ=28, β=8/3", "三初值相差 1e-5"),
            tools_needed=(ToolNeed(op=ToolOp.LORENZ_ENSEMBLE, params={"delta": 1e-5}),),
            output_duration_seconds=12.0,
            dimension="3d",
            category_hint=CodeGenerationCategory.THREE_D,
        )
    if _PID.search(text):
        return IntentSpec(
            domain=IntentDomain.CONTROL,
            goal="compare PID responses",
            assumptions=("归一化二阶对象", "三组 PID 参数预计算，不做连续调参"),
            tools_needed=(ToolNeed(op=ToolOp.PID_STEP_RESPONSE, params={}),),
            output_duration_seconds=12.0,
            dimension="2d",
            category_hint=CodeGenerationCategory.FUNCTION_VISUALIZATION,
        )
    if _CSV.search(text):
        return IntentSpec(
            domain=IntentDomain.DATA_ANALYSIS,
            goal="show temporal anomaly",
            assumptions=("使用上传 CSV 的 time/temperature/pressure 列", "禁止伪造科研数据"),
            tools_needed=(ToolNeed(op=ToolOp.CSV_ANOMALY, params={"center": 350.0}),),
            output_duration_seconds=12.0,
            dimension="2d",
            asset_required=not bool(csv_text and csv_text.strip()),
            asset_kind="csv",
            category_hint=CodeGenerationCategory.FUNCTION_VISUALIZATION,
        )
    if _FRENET.search(text):
        return IntentSpec(
            domain=IntentDomain.GEOMETRY_DIFF3D,
            goal="show Frenet frame on a helix",
            assumptions=("螺旋线 r(s)=(a cos s, a sin s, b s)", "T/N/B 由预计算导数得到"),
            tools_needed=(ToolNeed(op=ToolOp.FRENET_FRAME, params={}),),
            output_duration_seconds=12.0,
            dimension="3d",
            category_hint=CodeGenerationCategory.THREE_D,
        )
    return IntentSpec(
        domain=IntentDomain.TEACHING,
        goal=text[:200],
        assumptions=("未匹配到 P0 科研切片，需要确认领域",),
        tools_needed=(),
        needs_confirmation=True,
        category_hint=CodeGenerationCategory.FORMULA_DERIVATION,
    )
