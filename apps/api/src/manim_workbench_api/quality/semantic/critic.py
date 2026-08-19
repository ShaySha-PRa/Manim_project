"""TIFA-style expression critic. Science stays on ToolRun assertions.

A VLM provider may only fill CriticJudgement JSON. It never writes Manim.
Without a provider, questions are answered from IR, compiled source, and tools.
"""

from __future__ import annotations

import json
from typing import Protocol

from manim_workbench_api.content_plans.models import ProviderMessage, ProviderResult
from manim_workbench_contracts import CriticFinding, CriticQuestionResult, CriticReport
from manim_workbench_contracts.animation_ir import (
    AnimationIR,
    CameraOpKind,
    ObjectType,
    TimelineOpKind,
)
from manim_workbench_contracts.intent import CriticAnswer, ToolRun
from pydantic import ValidationError

CRITIC_SYSTEM_PROMPT = (
    "You fill CriticJudgement JSON for an animation expression critic. "
    "Return a single JSON object. Do not use markdown fences. "
    "Do not write Manim, Python, lambdas, or NumPy. "
    "Schema: {\"answers\":[{\"id\":\"q1\",\"answer\":\"yes\"}],\"findings\":[]}. "
    "answer must be yes or no. findings items: "
    "{\"code\":\"missing_zoom\",\"message\":\"...\",\"repairable\":true}."
)

_REPAIR_CODES = frozenset(
    {
        "missing_zoom",
        "missing_highlight",
        "missing_compare",
        "missing_3d_camera",
        "missing_title",
    }
)


class CriticJsonProvider(Protocol):
    def generate(self, messages: tuple[ProviderMessage, ...]) -> ProviderResult: ...


def evaluate_expression(
    ir: AnimationIR,
    tool_runs: tuple[ToolRun, ...],
    source: str,
    *,
    provider: CriticJsonProvider | None = None,
) -> CriticReport:
    questions = _offline_questions(ir, tool_runs, source)
    findings = _offline_findings(ir)
    vlm_used = False
    if provider is not None:
        try:
            vlm_questions, extra = _merge_vlm(provider, ir, questions)
            questions = vlm_questions
            findings = tuple(list(findings) + list(extra))
            vlm_used = True
        except (ValueError, json.JSONDecodeError, TypeError, ValidationError):
            vlm_used = False
    passed = sum(1 for item in questions if item.answer is item.expected)
    total = max(len(questions), 1)
    score = round(1.0 + 4.0 * (passed / total), 2)
    return CriticReport(
        expression_score=min(5.0, max(1.0, score)),
        vlm_used=vlm_used,
        questions=questions,
        findings=findings,
    )


def _offline_questions(
    ir: AnimationIR,
    tool_runs: tuple[ToolRun, ...],
    source: str,
) -> tuple[CriticQuestionResult, ...]:
    object_types = {item.type for item in ir.objects}
    ops = {item.op for item in ir.timeline}
    cameras = {item.op for item in ir.camera}
    assertions = {item.type.value for item in ir.assertions}
    tool_ok = True
    for key in assertions:
        if not any(bool(run.assertions.get(key)) for run in tool_runs):
            tool_ok = False
            break
    items = [
        _yes("has_title", "画面有标题", ObjectType.TITLE in object_types, "ir"),
        _yes("tool_science", "ToolRun 科学断言成立", tool_ok, "tool"),
        _yes("no_lambda", "编译结果不含 lambda", "lambda" not in source, "source"),
        _yes("no_pickle", "数组只读且禁止 pickle", "allow_pickle=False" in source, "source"),
    ]
    if ir.scene.dimension == "3d":
        items.append(
            _yes(
                "three_d_camera",
                "三维场景有相机朝向",
                CameraOpKind.SET_ORIENTATION in cameras,
                "ir",
            )
        )
        items.append(
            _yes("three_d_source", "编译为 ThreeDScene", "ThreeDScene" in source, "source")
        )
    if any(item.type.value == "gibbs_overshoot" for item in ir.assertions):
        items.append(
            _yes("gibbs_zoom", "Gibbs 使用 zoom camera", CameraOpKind.ZOOM in cameras, "ir")
        )
    if ObjectType.REGION in object_types:
        items.append(
            _yes("anomaly_highlight", "异常区域被 highlight", TimelineOpKind.HIGHLIGHT in ops, "ir")
        )
    if ir.pattern.value == "comparison":
        compared = TimelineOpKind.COMPARE in ops or TimelineOpKind.ANIMATE_STATE in ops
        items.append(_yes("compare_timeline", "对比时间线存在", compared, "ir"))
    return tuple(items)


def _offline_findings(ir: AnimationIR) -> tuple[CriticFinding, ...]:
    findings: list[CriticFinding] = []
    object_types = {item.type for item in ir.objects}
    ops = {item.op for item in ir.timeline}
    cameras = {item.op for item in ir.camera}
    if ObjectType.TITLE not in object_types:
        findings.append(_finding("missing_title", "缺少标题"))
    if ir.scene.dimension == "3d" and CameraOpKind.SET_ORIENTATION not in cameras:
        findings.append(_finding("missing_3d_camera", "三维缺少相机朝向"))
    if any(item.type.value == "gibbs_overshoot" for item in ir.assertions):
        if CameraOpKind.ZOOM not in cameras:
            findings.append(_finding("missing_zoom", "Gibbs 缺少 zoom"))
    if ObjectType.REGION in object_types and TimelineOpKind.HIGHLIGHT not in ops:
        findings.append(_finding("missing_highlight", "异常区域缺少 highlight"))
    if (
        ir.pattern.value == "comparison"
        and TimelineOpKind.COMPARE not in ops
        and TimelineOpKind.ANIMATE_STATE not in ops
    ):
        findings.append(_finding("missing_compare", "对比切片缺少 compare"))
    return tuple(findings)


def _merge_vlm(
    provider: CriticJsonProvider,
    ir: AnimationIR,
    questions: tuple[CriticQuestionResult, ...],
) -> tuple[tuple[CriticQuestionResult, ...], tuple[CriticFinding, ...]]:
    payload = json.dumps(
        {
            "goal": ir.goal,
            "pattern": ir.pattern.value,
            "questions": [{"id": item.id, "question": item.question} for item in questions],
        },
        ensure_ascii=False,
    )
    result = provider.generate(
        (
            ProviderMessage(role="system", content=CRITIC_SYSTEM_PROMPT),
            ProviderMessage(role="user", content=payload[:8_000]),
        )
    )
    text = result.content.strip()
    if text.startswith("```") or "from manim" in text.lower() or "lambda" in text.lower():
        raise ValueError("CriticJudgement must not contain Manim Python")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("CriticJudgement must be an object")
    answers = {
        item["id"]: item["answer"]
        for item in data.get("answers", [])
        if isinstance(item, dict)
    }
    merged: list[CriticQuestionResult] = []
    for item in questions:
        raw = answers.get(item.id)
        if raw in {"yes", "no"}:
            merged.append(item.model_copy(update={"answer": CriticAnswer(raw), "evidence": "vlm"}))
        else:
            merged.append(item)
    extra: list[CriticFinding] = []
    for item in data.get("findings", []):
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", ""))
        if code not in _REPAIR_CODES:
            continue
        extra.append(
            CriticFinding(
                code=code,
                message=str(item.get("message", code))[:300],
                repairable=True,
            )
        )
    return tuple(merged), tuple(extra)


def _yes(qid: str, question: str, passed: bool, evidence: str) -> CriticQuestionResult:
    return CriticQuestionResult(
        id=qid,
        question=question,
        answer=CriticAnswer.YES if passed else CriticAnswer.NO,
        expected=CriticAnswer.YES,
        evidence=evidence,  # type: ignore[arg-type]
    )


def _finding(code: str, message: str) -> CriticFinding:
    return CriticFinding(code=code, message=message, repairable=True)
