from __future__ import annotations

import pytest
from manim_workbench_api.content_plans.models import ProviderResult

from scripts.phase7_real_evaluation import RealPhase7Runner, _parse_quality_scores


class RecordingJudgeProvider:
    def __init__(self) -> None:
        self.messages = ()

    def generate(self, messages):  # type: ignore[no-untyped-def]
        self.messages = messages
        return ProviderResult(
            content='{"math_score":4,"visual_score":4}',
            finish_reason="stop",
            request_id="judge-test",
            model="judge-test",
        )


def test_quality_score_parser_keeps_only_bounded_scores() -> None:
    assert _parse_quality_scores(
        '{"math_score":4,"visual_score":5,"explanation":"not persisted"}'
    ) == (4, 5)


@pytest.mark.parametrize(
    "payload",
    (
        "not-json",
        "[]",
        '{"math_score":6,"visual_score":4}',
        '{"math_score":true,"visual_score":4}',
        '{"math_score":4}',
    ),
)
def test_quality_score_parser_rejects_invalid_scores(payload: str) -> None:
    with pytest.raises(ValueError):
        _parse_quality_scores(payload)


def test_quality_judge_uses_the_frozen_render_succeeded_visual_rubric() -> None:
    provider = RecordingJudgeProvider()
    runner = RealPhase7Runner(provider=provider, renderer=object())  # type: ignore[arg-type]

    scores = runner._judge(  # noqa: SLF001
        {
            "category": "formula_derivation",
            "teaching_goal": "show steps",
            "must_include": [],
            "must_avoid": [],
            "correctness_checks": [],
            "expected_scene_structure": [],
        },
        "from manim import Scene",
    )

    assert scores == (4, 4)
    system_prompt = provider.messages[0].content
    assert "already rendered successfully" in system_prompt
    assert "Unicode formulas rendered with Text are valid" in system_prompt
    assert "Give visual_score 4" in system_prompt
