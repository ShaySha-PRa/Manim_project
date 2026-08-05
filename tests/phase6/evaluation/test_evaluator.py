from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from benchmarks.phase6.evaluator import (
    FailureInjection,
    GenerationOutput,
    Phase6Evaluator,
    _default_formula_parser,
    load_gold_prompts,
    main,
)


def _entry(identifier: str = "formula_001") -> dict[str, object]:
    return {
        "id": identifier,
        "category": "formula_derivation",
        "topic": "一元一次方程",
        "prompt": "请推导 3x-5=16。",
        "duration_seconds": {"target": 60},
    }


def _ready_response(title: str = "一元一次方程") -> str:
    return json.dumps(
        {
            "outcome": "ready",
            "plan": {
                "schema_version": "1.1",
                "title": title,
                "audience": "high_school",
                "language": "zh-CN",
                "target_duration_seconds": 60,
                "derivation_style": "step_by_step",
                "explicit_assumptions": ["学习者了解等式性质。"],
                "ambiguities": [],
                "scenes": [
                    {
                        "scene_number": 1,
                        "teaching_goal": "保持等式平衡。",
                        "formula_steps": [
                            {"expression": "3x-5=16", "explanation": "原方程。"},
                            {"expression": "x=7", "explanation": "两边同除以3。"},
                        ],
                        "visual_intent": "显示等式两边同步变化。",
                        "narration_placeholder": "解释等式性质。",
                    }
                ],
            },
        },
        ensure_ascii=False,
    )


def _constant_generator(output: object) -> Callable[[dict[str, object], int], object]:
    return lambda _entry, _attempt: output


def test_evaluator_calculates_all_four_metrics_for_a_valid_ready_plan() -> None:
    evaluator = Phase6Evaluator(
        generator=_constant_generator(_ready_response()),
        semantic_validator=lambda _response: True,
        formula_parser=lambda expression: expression in {"3x-5=16", "x=7"},
    )

    report = evaluator.evaluate([_entry()])

    record = report.records[0]
    assert record.schema_valid is True
    assert record.semantic_valid is True
    assert record.formula_parse_success is True
    assert record.actionable_outcome is True
    assert report.schema_valid_rate == 1.0
    assert report.semantic_valid_rate == 1.0
    assert report.formula_parse_success_rate == 1.0


@pytest.mark.parametrize(
    ("failure", "expected_code", "schema_valid", "semantic_valid"),
    [
        (FailureInjection.EMPTY, "provider_empty_response", False, False),
        (FailureInjection.TRUNCATED, "provider_truncated_response", False, False),
        (FailureInjection.INVALID_JSON, "provider_invalid_json", False, False),
        (FailureInjection.SCHEMA, "provider_schema_error", False, False),
        (FailureInjection.SEMANTIC, "content_plan_semantic_error", True, False),
    ],
)
def test_evaluator_classifies_required_failure_injections(
    failure: FailureInjection,
    expected_code: str,
    schema_valid: bool,
    semantic_valid: bool,
) -> None:
    evaluator = Phase6Evaluator(
        generator=Phase6Evaluator.failure_injected_generator(
            _constant_generator(_ready_response()), failure
        ),
        semantic_validator=lambda _response: True,
    )

    record = evaluator.evaluate([_entry()]).records[0]

    assert record.error_code == expected_code
    assert record.schema_valid is schema_valid
    assert record.semantic_valid is semantic_valid
    assert record.actionable_outcome is True


def test_evaluator_applies_phase6_gates_to_thirty_entries_and_reports_stability() -> None:
    entries = [_entry(f"formula_{index:03d}") for index in range(1, 31)]
    evaluator = Phase6Evaluator(
        generator=_constant_generator(_ready_response()), semantic_validator=lambda _response: True
    )

    report = evaluator.evaluate(entries, repetitions=3)

    assert report.input_count == 30
    assert report.schema_valid_count == 30
    assert report.semantic_valid_count == 30
    assert report.formula_parse_success_count == 30
    assert report.gates_passed is True
    assert report.structure_stability_rate == 1.0
    assert all(record.structure_stable is True for record in report.records)


def test_evaluator_marks_changing_response_shapes_as_unstable_without_failing_gates() -> None:
    clarification = json.dumps(
        {
            "outcome": "needs_clarification",
            "clarifications": [
                {"field": "audience", "question": "面向哪个年级？", "options": []}
            ],
        },
        ensure_ascii=False,
    )

    evaluator = Phase6Evaluator(
        generator=lambda _entry, attempt: _ready_response() if attempt == 1 else clarification,
        semantic_validator=lambda _response: True,
    )

    report = evaluator.evaluate([_entry()], repetitions=3)

    assert report.gates_passed is False
    assert report.structure_stability_rate == 0.0
    assert report.records[0].structure_stable is False


def test_phase6_gates_require_the_fixed_thirty_prompt_gold_set() -> None:
    evaluator = Phase6Evaluator(
        generator=_constant_generator(_ready_response()), semantic_validator=lambda _response: True
    )

    report = evaluator.evaluate([_entry()])

    assert report.schema_required_count == 29
    assert report.semantic_required_count == 27
    assert report.formula_required_count == 29
    assert report.gates_passed is False


def test_report_is_jsonl_and_never_persists_provider_text_or_sensitive_markers(
    tmp_path: Path,
) -> None:
    sensitive_output = GenerationOutput(content="sk-live-token-must-never-be-persisted")
    evaluator = Phase6Evaluator(generator=_constant_generator(sensitive_output))
    report = evaluator.evaluate([_entry()])
    output_path = tmp_path / "phase6-report.jsonl"

    evaluator.write_jsonl_report(output_path, report)

    saved = output_path.read_text(encoding="utf-8").lower()
    assert "sk-live-token" not in saved
    assert "authorization" not in saved
    assert "system_prompt" not in saved
    assert len(saved.splitlines()) == 2
    assert json.loads(saved.splitlines()[0])["record_type"] == "phase6-evaluation-summary-v1"


def test_cli_evaluates_fixture_without_provider_access(tmp_path: Path) -> None:
    gold_path = tmp_path / "gold.jsonl"
    fixture_path = tmp_path / "fixture.jsonl"
    output_path = tmp_path / "report.jsonl"
    gold_path.write_text(json.dumps(_entry()) + "\n", encoding="utf-8")
    fixture_path.write_text(
        json.dumps({"id": "formula_001", "content": _ready_response()}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    assert (
        main(
            [
                "--gold-set",
                str(gold_path),
                "--fixture",
                str(fixture_path),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )

    summary = json.loads(output_path.read_text(encoding="utf-8").splitlines()[0])
    assert summary["schema_valid_count"] == 1


def test_load_gold_prompts_reads_the_repository_gold_set_without_writing_it() -> None:
    gold_path = Path(__file__).resolve().parents[3] / "eval" / "gold_prompts.jsonl"
    before = gold_path.read_bytes()

    entries = load_gold_prompts(gold_path)

    assert len(entries) == 30
    assert gold_path.read_bytes() == before


def test_formula_parser_accepts_semicolon_in_piecewise_mathematics() -> None:
    assert _default_formula_parser("f(x)=x², x<1; f(x)=x, x≥1") is True
