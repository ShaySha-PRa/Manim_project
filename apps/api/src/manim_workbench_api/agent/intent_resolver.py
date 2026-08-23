"""Resolve one-sentence prompts into IntentSpec. LLM may only fill this JSON."""

from __future__ import annotations

import json
import re
from typing import Protocol

from manim_workbench_contracts import IntentSpec, ToolNeed, ToolOp
from manim_workbench_contracts.intent import IntentDomain
from manim_workbench_contracts.models import CodeGenerationCategory
from pydantic import ValidationError

from manim_workbench_api.agent.paper_catalog import match_paper_catalog
from manim_workbench_api.content_plans.models import ProviderMessage, ProviderResult

_WAVE = re.compile(r"波包|干涉|wave.?packet|interfer", re.I)
_FOURIER = re.compile(r"傅里叶|傅立叶|gibbs|方波|fourier", re.I)
_FOURIER_N_MAX = re.compile(
    r"(?:n\s*=\s*(\d{1,3})|(?:增加到|增至|up\s+to)\s*(\d{1,3})|"
    r"(\d{1,3})\s*(?:个|项)\s*(?:奇次)?谐波)",
    re.I,
)
_LORENZ = re.compile(r"lorenz|洛伦兹", re.I)
_PID = re.compile(r"\bpid\b|阶跃响应|超调", re.I)
_CSV = re.compile(r"csv|异常|temperature|pressure|时序", re.I)
_CSV_CENTER = re.compile(
    r"(?:"
    r"(?:time|timestamp|t|时间)\s*=\s*(\d+(?:\.\d+)?)"
    r"|(?:near|around|at|附近|接近|位于)?\s*(\d+(?:\.\d+)?)\s*(?:s|sec|seconds?|秒)"
    r")",
    re.I,
)
_FRENET = re.compile(r"frenet|切向量|法向量|副法|螺旋|helix|tnb", re.I)
_PAPER = re.compile(
    r"论文|\.pdf\b|paper model|paper ode|scientific reproduction|"
    r"实验 CSV|实验数据|lotka|volterra|洛特卡",
    re.I,
)

INTENT_SYSTEM_PROMPT = (
    "You fill IntentSpec JSON for an Animation Agent. "
    "Return a single JSON object. Do not use markdown fences. "
    "Do not write Manim, Python, lambdas, or NumPy. "
    "Return exactly these fields and no others: schema_version, domain, goal, assumptions, "
    "tools_needed, output_duration_seconds, dimension, needs_confirmation, asset_required, "
    'asset_kind, category_hint. schema_version must be the JSON string "1.0", not a number. '
    "assumptions must be an array of strings. tools_needed must be an array of objects shaped "
    'exactly as {"op":"allowed_tool_name","params":{}}; never return tool names as '
    "bare strings and never add a top-level parameters field. Every numeric parameter must be "
    "a finite JSON number; evaluate expressions such as 8/3 before returning JSON. "
    "Tool params are a closed scalar-only contract: wave2d_superposition allows only c and k; "
    "fourier_square_wave allows only n_max; lorenz_ensemble allows only delta; "
    "pid_step_response allows no params; csv_anomaly allows only center; frenet_frame allows no "
    "params. Never return arrays, objects, initial_conditions, duration, dt, sigma, rho, or beta "
    "inside params. ode_compare params are supplied only after the server matches its closed "
    "paper catalog; do not invent them. "
    "For csv_anomaly, include center only when the user explicitly supplies a numeric time; "
    "otherwise return empty params so the deterministic kernel detects the anomaly. "
    'output_duration_seconds must be a number, dimension must be "2d" or "3d", '
    "needs_confirmation and asset_required must be booleans, and asset_kind must be a string "
    "or null. category_hint must be one of formula_derivation, function_visualization, "
    "plane_geometry, geometry_proof, three_d, or mixed. "
    "Allowed domains: physics.wave, math.signal, dynamical_systems, "
    "control, data_analysis, geometry.diff3d, scientific_reproduction, teaching. "
    "Allowed tools: wave2d_superposition, fourier_square_wave, lorenz_ensemble, "
    "pid_step_response, csv_anomaly, frenet_frame, ode_compare. "
    "If the prompt is not one of those compiled slices, set needs_confirmation "
    "true and tools_needed to []. "
    "If the prompt needs a paper/PDF and PAPER_MATCHED=false, use domain "
    "scientific_reproduction, needs_confirmation true, and do not invent equations. "
    "If PAPER_MATCHED=true and CSV_PRESENT=true, use ode_compare and "
    "needs_confirmation false. "
    "If the prompt needs CSV and none is provided, set asset_required true "
    "and asset_kind csv, set needs_confirmation false, and do not request a tool run. "
    "schema_version must be 1.0."
)


class IntentJsonProvider(Protocol):
    def generate(self, messages: tuple[ProviderMessage, ...]) -> ProviderResult: ...


def intent_from_llm_json(payload: str) -> IntentSpec:
    """Parse model output that must be IntentSpec JSON only."""
    text = payload.strip()
    if text.startswith("```"):
        raise ValueError("IntentSpec JSON must not be fenced")
    lowered = text.lower()
    if "class generatedscene" in lowered or "from manim" in lowered:
        raise ValueError("IntentSpec must not contain Manim Python")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("IntentSpec must be an object")
    try:
        return IntentSpec.model_validate(data)
    except ValidationError as error:
        raise ValueError("IntentSpec JSON is invalid") from error


def fill_intent_from_provider(
    provider: IntentJsonProvider,
    prompt: str,
    *,
    csv_text: str | None = None,
    paper_text: str | None = None,
) -> IntentSpec:
    matched = match_paper_catalog(paper_text or "", csv_text)
    user = prompt.strip()
    user += f"\n\nCSV_PRESENT={'true' if csv_text and csv_text.strip() else 'false'}"
    user += f"\nPAPER_MATCHED={'true' if matched is not None else 'false'}"
    result = provider.generate(
        (
            ProviderMessage(role="system", content=INTENT_SYSTEM_PROMPT),
            ProviderMessage(role="user", content=user[:20_000]),
        )
    )
    return _post_validate(
        intent_from_llm_json(result.content),
        prompt=prompt,
        csv_text=csv_text,
        paper_text=paper_text,
    )


def resolve_intent(
    prompt: str,
    *,
    csv_text: str | None = None,
    paper_text: str | None = None,
    provider: IntentJsonProvider | None = None,
) -> IntentSpec:
    if provider is not None:
        try:
            return fill_intent_from_provider(
                provider, prompt, csv_text=csv_text, paper_text=paper_text
            )
        except (ValueError, json.JSONDecodeError, TypeError):
            return _needs_confirmation(prompt, "IntentSpec JSON 无法校验")
    return resolve_intent_catalog(prompt, csv_text=csv_text, paper_text=paper_text)


def resolve_intent_catalog(
    prompt: str,
    *,
    csv_text: str | None = None,
    paper_text: str | None = None,
) -> IntentSpec:
    text = prompt.strip()
    if _PAPER.search(text):
        return _paper_intent(text, csv_text=csv_text, paper_text=paper_text)
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
    return _needs_confirmation(text, "未匹配到已编译科研切片，需要确认领域")


def _paper_intent(
    prompt: str,
    *,
    csv_text: str | None,
    paper_text: str | None,
) -> IntentSpec:
    matched = match_paper_catalog(paper_text or "", csv_text)
    if matched is None:
        missing_paper = not (paper_text and paper_text.strip())
        return IntentSpec(
            domain=IntentDomain.SCIENTIFIC_REPRODUCTION,
            goal="compare paper model with experiment",
            assumptions=("方程提取置信不足，不能自行补公式",),
            tools_needed=(),
            needs_confirmation=True,
            asset_required=missing_paper,
            asset_kind="pdf" if missing_paper else None,
            category_hint=CodeGenerationCategory.FUNCTION_VISUALIZATION,
        )
    if not (csv_text and csv_text.strip()):
        return IntentSpec(
            domain=IntentDomain.SCIENTIFIC_REPRODUCTION,
            goal="compare paper model with experiment",
            assumptions=("已匹配 Lotka-Volterra 目录，仍需实验 CSV",),
            tools_needed=(),
            asset_required=True,
            asset_kind="csv",
            category_hint=CodeGenerationCategory.FUNCTION_VISUALIZATION,
        )
    return IntentSpec(
        domain=IntentDomain.SCIENTIFIC_REPRODUCTION,
        goal="compare paper model with experiment",
        assumptions=(
            f"catalog:{matched.system}",
            f"alpha={matched.alpha}, beta={matched.beta}, "
            f"gamma={matched.gamma}, delta={matched.delta}",
        ),
        tools_needed=(
            ToolNeed(
                op=ToolOp.ODE_COMPARE,
                params={
                    "system": matched.system,
                    "alpha": matched.alpha,
                    "beta": matched.beta,
                    "gamma": matched.gamma,
                    "delta": matched.delta,
                    "time_column": matched.time_column,
                    "x_column": matched.x_column,
                    "y_column": matched.y_column,
                },
            ),
        ),
        output_duration_seconds=12.0,
        dimension="2d",
        category_hint=CodeGenerationCategory.FUNCTION_VISUALIZATION,
    )


def _post_validate(
    spec: IntentSpec,
    *,
    prompt: str,
    csv_text: str | None,
    paper_text: str | None,
) -> IntentSpec:
    if spec.domain is IntentDomain.SCIENTIFIC_REPRODUCTION:
        return _paper_intent(spec.goal, csv_text=csv_text, paper_text=paper_text)
    if spec.domain is IntentDomain.DATA_ANALYSIS and not (csv_text and csv_text.strip()):
        return spec.model_copy(
            update={
                "tools_needed": (),
                "needs_confirmation": False,
                "asset_required": True,
                "asset_kind": "csv",
            }
        )
    if spec.domain is IntentDomain.DATA_ANALYSIS:
        match = _CSV_CENTER.search(prompt)
        center = (
            next((group for group in match.groups() if group is not None), None) if match else None
        )
        params = {"center": float(center)} if center is not None else {}
        return spec.model_copy(
            update={"tools_needed": (ToolNeed(op=ToolOp.CSV_ANOMALY, params=params),)}
        )
    if spec.domain is IntentDomain.MATH_SIGNAL:
        requested = _explicit_fourier_n_max(prompt)
        if requested is not None:
            if not 1 <= requested <= 63:
                return _needs_confirmation(prompt, "请求的 Fourier 谐波上限超出 1..63")
            return spec.model_copy(
                update={
                    "tools_needed": (
                        ToolNeed(op=ToolOp.FOURIER_SQUARE_WAVE, params={"n_max": requested}),
                    )
                }
            )
    if spec.domain is IntentDomain.TEACHING and not spec.tools_needed:
        return spec.model_copy(update={"needs_confirmation": True})
    return spec


def _explicit_fourier_n_max(prompt: str) -> int | None:
    values = [
        int(group)
        for match in _FOURIER_N_MAX.finditer(prompt)
        for group in match.groups()
        if group is not None
    ]
    return max(values) if values else None


def _needs_confirmation(prompt: str, assumption: str) -> IntentSpec:
    return IntentSpec(
        domain=IntentDomain.TEACHING,
        goal=prompt.strip()[:200],
        assumptions=(assumption,),
        tools_needed=(),
        needs_confirmation=True,
        category_hint=CodeGenerationCategory.FORMULA_DERIVATION,
    )
