from __future__ import annotations

import json
from pathlib import Path

import pytest
from manim_workbench_api.content_plans.models import ProviderResult
from manim_workbench_contracts import Audience, DerivationStyle

from scripts.phase6_real_evaluation import (
    RealGoldGenerator,
    load_deepseek_key,
    request_for_entry,
)


def gold_entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": "formula_001",
        "category": "formula_derivation",
        "audience": "k12",
        "persona": "高中数学教师",
        "prompt": "请推导 3x-5=16。",
        "duration_seconds": {"target": 60},
    }
    entry.update(overrides)
    return entry


def ready_json() -> str:
    return json.dumps(
        {
            "outcome": "ready",
            "plan": {
                "schema_version": "1.1",
                "title": "一元一次方程",
                "audience": "high_school",
                "language": "zh-CN",
                "target_duration_seconds": 60,
                "derivation_style": "step_by_step",
                "explicit_assumptions": [],
                "ambiguities": [],
                "scenes": [
                    {
                        "scene_number": 1,
                        "teaching_goal": "保持等式平衡。",
                        "formula_steps": [
                            {"expression": "3x-5=16", "explanation": "原方程。"},
                            {"expression": "x=7", "explanation": "完成求解。"},
                        ],
                        "visual_intent": "展示等式两侧同步变化。",
                        "narration_placeholder": "解释等式性质。",
                    }
                ],
            },
        },
        ensure_ascii=False,
    )


class SequenceProvider:
    def __init__(self, contents: list[str]) -> None:
        self.contents = iter(contents)
        self.calls = 0

    def generate(self, messages):  # type: ignore[no-untyped-def]
        self.calls += 1
        return ProviderResult(
            content=next(self.contents),
            model="deepseek-v4-flash",
        )


def test_load_deepseek_key_reads_only_requested_value(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("UNRELATED=value\nDEEPSEEK_API_KEY='test-secret'\n", encoding="utf-8")

    assert load_deepseek_key(env_path) == "test-secret"


def test_load_deepseek_key_rejects_missing_or_empty_value(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("DEEPSEEK_API_KEY=\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not configured"):
        load_deepseek_key(env_path)


def test_request_for_entry_maps_gold_preferences_deterministically() -> None:
    request = request_for_entry(gold_entry())

    assert request.audience is Audience.HIGH_SCHOOL
    assert request.target_duration_seconds == 60
    assert request.derivation_style is DerivationStyle.STEP_BY_STEP
    assert request.explicit_assumptions == ()


def test_request_for_entry_maps_general_creator_to_supported_audience() -> None:
    request = request_for_entry(
        gold_entry(audience="general_creator", persona="数学科普创作者")
    )

    assert request.audience is Audience.GENERAL_AUDIENCE


def test_real_generator_retries_invalid_json_once_without_saving_raw_output() -> None:
    provider = SequenceProvider(["{invalid", ready_json()])
    generator = RealGoldGenerator(provider)

    output = generator.generate(gold_entry(), 1)

    assert provider.calls == 2
    assert output.content == ready_json()
    assert output.error_code is None
    assert generator.current_request is not None
    assert generator.current_source_prompt == "请推导 3x-5=16。"
