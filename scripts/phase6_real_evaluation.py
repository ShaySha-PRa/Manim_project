from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from manim_workbench_api.content_plans.errors import ContentPlanError, ContentPlanSemanticError
from manim_workbench_api.content_plans.prompts import build_content_plan_messages
from manim_workbench_api.content_plans.provider import DeepSeekProvider
from manim_workbench_api.content_plans.service import ContentPlanService
from manim_workbench_api.content_plans.validation import validate_content_plan_response
from manim_workbench_contracts import (
    Audience,
    ContentPlanGenerationRequest,
    ContentPlanModelResponse,
    DerivationStyle,
    Language,
)

from benchmarks.phase6.evaluator import GenerationOutput, Phase6Evaluator, load_gold_prompts

GoldEntry = Mapping[str, Any]


def load_deepseek_key(path: Path) -> str:
    """Read one local dotenv key without evaluating the file as shell code."""
    values: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, raw_value = line.split("=", 1)
        if name.strip() != "DEEPSEEK_API_KEY":
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values.append(value)
    if len(values) != 1 or not values[0]:
        raise ValueError("DEEPSEEK_API_KEY is not configured exactly once")
    return values[0]


def request_for_entry(entry: GoldEntry) -> ContentPlanGenerationRequest:
    identifier = _required_string(entry, "id")
    category = _required_string(entry, "category")
    prompt = _required_string(entry, "prompt")
    del prompt
    duration = entry.get("duration_seconds")
    if not isinstance(duration, Mapping) or not isinstance(duration.get("target"), int):
        raise ValueError(f"{identifier}: duration_seconds.target must be an integer")
    target_duration = int(duration["target"])
    audience = _audience_for_entry(entry)
    style = (
        DerivationStyle.STEP_BY_STEP
        if category == "formula_derivation"
        else DerivationStyle.VISUAL_INTUITION
    )
    stable_id = uuid5(NAMESPACE_URL, f"manim-workbench:phase6:{identifier}")
    return ContentPlanGenerationRequest(
        project_id=stable_id,
        owner_id=stable_id,
        prompt_version_id=stable_id,
        audience=audience,
        language=Language.ZH_CN,
        target_duration_seconds=target_duration,
        derivation_style=style,
        explicit_assumptions=(),
    )


def _audience_for_entry(entry: GoldEntry) -> Audience | None:
    audience = entry.get("audience")
    if audience == "college":
        return Audience.UNDERGRADUATE
    if audience == "k12":
        persona = str(entry.get("persona", ""))
        if "小学" in persona:
            return Audience.PRIMARY_SCHOOL
        if "初中" in persona and "高中" not in persona:
            return Audience.MIDDLE_SCHOOL
        return Audience.HIGH_SCHOOL
    if audience == "general_creator":
        return Audience.GENERAL_AUDIENCE
    raise ValueError(f"unsupported gold audience: {audience!r}")


def _required_string(entry: GoldEntry, field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"gold entry requires non-empty {field}")
    return value


class RealGoldGenerator:
    """Adapter that keeps raw provider content in memory only."""

    def __init__(self, provider: DeepSeekProvider) -> None:
        self._provider = provider
        self.current_request: ContentPlanGenerationRequest | None = None
        self.current_source_prompt: str | None = None
        self.current_prompt_id: str | None = None
        self.semantic_errors: dict[str, str] = {}

    def generate(self, entry: GoldEntry, _repetition: int) -> GenerationOutput:
        request = request_for_entry(entry)
        prompt_id = _required_string(entry, "id")
        source_prompt = _required_string(entry, "prompt")
        self.current_request = request
        self.current_source_prompt = source_prompt
        self.current_prompt_id = prompt_id
        messages = build_content_plan_messages(source_prompt, request)
        for attempt in (1, 2):
            try:
                result = self._provider.generate(messages)
                ContentPlanService._parse(result)
            except ContentPlanError as error:
                if error.retryable and attempt == 1:
                    continue
                return GenerationOutput(content=None, error_code=error.code.value)
            return GenerationOutput(
                content=result.content,
                finish_reason=result.finish_reason,
            )
        raise AssertionError("two-attempt loop must return")

    def validate_semantics(self, response: ContentPlanModelResponse) -> bool:
        if self.current_request is None or self.current_source_prompt is None:
            raise RuntimeError("generator state is unavailable")
        try:
            validate_content_plan_response(
                response,
                self.current_request,
                self.current_source_prompt,
            )
        except ContentPlanSemanticError as error:
            if self.current_prompt_id is not None:
                self.semantic_errors[self.current_prompt_id] = str(error)
            raise
        return True


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run redacted real DeepSeek Phase 6 evaluation")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--gold-set", type=Path, default=Path("eval/gold_prompts.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, choices=range(1, 31))
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--repetitions", type=int, choices=(1, 3), default=1)
    parser.add_argument("--diagnostics", action="store_true")
    arguments = parser.parse_args(argv)

    os.environ["DEEPSEEK_API_KEY"] = load_deepseek_key(arguments.env_file)
    entries = load_gold_prompts(arguments.gold_set)
    if arguments.ids:
        requested_ids = set(arguments.ids)
        entries = tuple(entry for entry in entries if entry["id"] in requested_ids)
        if {entry["id"] for entry in entries} != requested_ids:
            raise ValueError("one or more requested gold IDs were not found")
    if arguments.limit is not None:
        entries = entries[: arguments.limit]

    adapter = RealGoldGenerator(DeepSeekProvider())
    evaluator = Phase6Evaluator(
        generator=adapter.generate,
        semantic_validator=adapter.validate_semantics,
    )
    report = evaluator.evaluate(entries, repetitions=arguments.repetitions)
    evaluator.write_jsonl_report(arguments.output, report)
    print(json.dumps(report.summary_dict(), ensure_ascii=False, sort_keys=True))
    if arguments.diagnostics:
        print(json.dumps({"semantic_errors": adapter.semantic_errors}, sort_keys=True))
    if arguments.limit is not None or arguments.ids:
        return 0 if report.actionable_outcome_count == len(entries) else 1
    return 0 if report.gates_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
