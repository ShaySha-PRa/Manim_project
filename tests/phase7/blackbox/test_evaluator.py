from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from benchmarks.phase7.evaluator import (
    ATTACK_CORPUS_VERSION,
    FailureInjection,
    Phase7Evaluator,
    RenderObservation,
    load_attack_corpus,
)


def _case(identifier: str) -> dict[str, str]:
    return {
        "id": identifier,
        "category": "formula_derivation",
        "prompt": "This raw prompt must never be written to a report.",
    }


def _passing_observation(*, duration_ms: float = 10.0) -> RenderObservation:
    return RenderObservation(
        first_render_succeeded=True,
        final_render_succeeded=True,
        security_blocked=False,
        sandbox_invocations=1,
        math_score=5,
        visual_score=5,
        attempts_used=1,
        duration_ms=duration_ms,
        candidate_source="from manim import Scene\nclass GeneratedScene(Scene): pass",
        diagnostic="/home/developer/projects/Manim_project/.env sk-live-should-not-appear",
    )


def _constant_runner(
    observation: RenderObservation,
) -> Callable[[dict[str, str], int], RenderObservation]:
    return lambda _case, _repetition: observation


def test_evaluator_applies_all_phase7_gates_to_thirty_gold_cases() -> None:
    evaluator = Phase7Evaluator(runner=_constant_runner(_passing_observation()))

    report = evaluator.evaluate([_case(f"gold-{index:02d}") for index in range(30)])

    assert report.first_render_rate == 1.0
    assert report.final_render_rate == 1.0
    assert report.math_quality_rate == 1.0
    assert report.visual_quality_rate == 1.0
    assert report.gates_passed is True


def test_evaluator_fails_the_specific_gate_that_falls_below_the_threshold() -> None:
    cases = [_case(f"gold-{index:02d}") for index in range(30)]

    def runner(case: dict[str, str], _repetition: int) -> RenderObservation:
        index = int(case["id"].split("-")[1])
        return RenderObservation(
            first_render_succeeded=index < 22,
            final_render_succeeded=index < 26,
            security_blocked=False,
            sandbox_invocations=1,
            math_score=4 if index < 26 else 3,
            visual_score=4 if index < 23 else 3,
            attempts_used=3,
            duration_ms=10.0,
        )

    report = Phase7Evaluator(runner=runner).evaluate(cases)

    assert report.first_render_rate == pytest.approx(22 / 30)
    assert report.final_render_rate == pytest.approx(26 / 30)
    assert report.math_quality_rate == pytest.approx(26 / 30)
    assert report.visual_quality_rate == pytest.approx(23 / 30)
    assert report.gates_passed is False
    assert report.gate_failures == (
        "first_render_rate",
        "final_render_rate",
        "math_quality_rate",
        "visual_quality_rate",
    )


def test_malicious_attack_corpus_is_versioned_and_requires_block_before_sandbox() -> None:
    corpus_path = (
        Path(__file__).resolve().parents[3]
        / "benchmarks"
        / "phase7"
        / "fixtures"
        / "malicious_attack_corpus.v1.json"
    )
    corpus = load_attack_corpus(corpus_path)
    sandbox_calls: list[str] = []

    def blocked_by_security_gate(candidate: str) -> bool:
        assert candidate
        return False

    report = Phase7Evaluator(runner=_constant_runner(_passing_observation())).evaluate_attacks(
        corpus,
        security_gate=blocked_by_security_gate,
        sandbox_probe=lambda attack_id: sandbox_calls.append(attack_id),
    )

    assert report.corpus_version == ATTACK_CORPUS_VERSION
    assert report.attack_count >= 8
    assert report.security_block_rate == 1.0
    assert report.sandbox_bypass_count == 0
    assert sandbox_calls == []


def test_combined_gates_fail_closed_when_one_security_attack_reaches_the_sandbox() -> None:
    corpus_path = (
        Path(__file__).resolve().parents[3]
        / "benchmarks"
        / "phase7"
        / "fixtures"
        / "malicious_attack_corpus.v1.json"
    )
    evaluator = Phase7Evaluator(runner=_constant_runner(_passing_observation()))
    gold_report = evaluator.evaluate([_case(f"gold-{index:02d}") for index in range(30)])
    attack_report = evaluator.evaluate_attacks(
        load_attack_corpus(corpus_path),
        security_gate=lambda source: source.startswith("__import__"),
    )

    assert attack_report.security_block_rate < 1.0
    assert attack_report.sandbox_bypass_count == 1
    assert Phase7Evaluator.combined_gates_passed(gold_report, attack_report) is False


@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        (FailureInjection.MODEL_RESPONSE, "invalid_model_response"),
        (FailureInjection.AST_PARSE, "ast_parse_failed"),
        (FailureInjection.COMPILE, "compile_failed"),
        (FailureInjection.SCENE_STRUCTURE, "scene_structure_invalid"),
        (FailureInjection.RENDER, "render_failed"),
        (FailureInjection.TIMEOUT, "sandbox_timeout"),
        (FailureInjection.RESOURCE_LIMIT, "sandbox_resource_limit"),
    ],
)
def test_failure_injection_is_offline_and_classified(
    failure: FailureInjection, expected_error: str
) -> None:
    evaluator = Phase7Evaluator(
        runner=Phase7Evaluator.failure_injected_runner(
            _constant_runner(_passing_observation()), failure
        )
    )

    record = evaluator.evaluate([_case("gold-01")]).records[0]

    assert record.error_code == expected_error
    assert record.final_render_succeeded is False
    assert record.attempts_used == 1


def test_repetitions_measure_candidate_hash_attempt_budget_policy_and_performance() -> None:
    def runner(_case: dict[str, str], repetition: int) -> RenderObservation:
        return RenderObservation(
            first_render_succeeded=True,
            final_render_succeeded=True,
            security_blocked=False,
            sandbox_invocations=1,
            math_score=5,
            visual_score=5,
            attempts_used=1 if repetition != 2 else 2,
            duration_ms=10.0 * repetition,
            candidate_source="stable-source" if repetition != 3 else "changed-source",
            policy_state="active",
        )

    report = Phase7Evaluator(runner=runner).evaluate([_case("gold-01")], repetitions=3)

    assert report.records[0].reproducible is False
    assert report.reproducibility_rate == 0.0
    assert report.performance.mean_duration_ms == pytest.approx(20.0)
    assert report.performance.p95_duration_ms == pytest.approx(29.0)


def test_jsonl_report_redacts_prompt_source_diagnostics_secrets_and_host_paths(
    tmp_path: Path,
) -> None:
    evaluator = Phase7Evaluator(runner=_constant_runner(_passing_observation()))
    report = evaluator.evaluate([_case("gold-01")])
    output_path = tmp_path / "phase7-report.jsonl"

    evaluator.write_jsonl_report(output_path, report)

    saved = output_path.read_text(encoding="utf-8").lower()
    assert "raw prompt" not in saved
    assert "generatedscene" not in saved
    assert "sk-live-should-not-appear" not in saved
    assert "/home/developer" not in saved
    assert len(saved.splitlines()) == 2
    assert json.loads(saved.splitlines()[0])["record_type"] == "phase7-evaluation-summary-v1"


def test_attack_report_never_serializes_malicious_candidate_source(tmp_path: Path) -> None:
    corpus_path = (
        Path(__file__).resolve().parents[3]
        / "benchmarks"
        / "phase7"
        / "fixtures"
        / "malicious_attack_corpus.v1.json"
    )
    evaluator = Phase7Evaluator(runner=_constant_runner(_passing_observation()))
    attack_report = evaluator.evaluate_attacks(
        load_attack_corpus(corpus_path), security_gate=lambda _candidate: False
    )
    output_path = tmp_path / "phase7-attacks.jsonl"

    evaluator.write_attack_jsonl_report(output_path, attack_report)

    saved = output_path.read_text(encoding="utf-8")
    assert "__import__" not in saved
    assert "subprocess" not in saved
    assert "candidate" not in saved.lower()
