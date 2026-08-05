from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

SCENES = (
    "formula_transform",
    "derivative",
    "function_plot",
    "parameter_sweep",
    "tangent",
    "area",
)
ENGINES = {"manimce", "manimgl"}
CAPABILITIES = ("visual_score", "sections_cache_score", "deployment_score")
WEIGHTS = {
    "stability": 0.40,
    "speed": 0.20,
    "first_attempt": 0.15,
    "visual": 0.10,
    "sections_cache": 0.10,
    "deployment": 0.05,
}


class ResultError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedResult:
    engine: str
    successful_runs: int
    mean_duration: float | None
    first_attempt_score: float
    visual_score: float
    sections_cache_score: float
    deployment_score: float


def _non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResultError(f"{field} must be a non-empty string")
    return value


def _bounded_score(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ResultError(f"{field} must be numeric")
    if not 0 <= value <= 100:
        raise ResultError(f"{field} must be between 0 and 100")
    return float(value)


def validate_result(raw: Any) -> ValidatedResult:
    if not isinstance(raw, dict):
        raise ResultError("result must be an object")
    engine = raw.get("engine")
    if engine not in ENGINES:
        raise ResultError(f"unsupported engine: {engine!r}")

    for field in (
        "engine_version",
        "python_version",
        "ffmpeg_version",
        "latex_version",
        "container_or_environment",
    ):
        _non_empty_string(raw.get(field), f"{engine}.{field}")
    fonts = raw.get("font_versions")
    if not isinstance(fonts, list) or not fonts:
        raise ResultError(f"{engine}.font_versions must be a non-empty list")
    for index, font in enumerate(fonts):
        _non_empty_string(font, f"{engine}.font_versions[{index}]")

    attempts = raw.get("first_attempt_success")
    if not isinstance(attempts, dict) or set(attempts) != set(SCENES):
        raise ResultError(f"{engine}.first_attempt_success must contain all six scenes")
    if any(not isinstance(value, bool) for value in attempts.values()):
        raise ResultError(f"{engine}.first_attempt_success values must be booleans")

    runs = raw.get("runs")
    if not isinstance(runs, list) or len(runs) != 12:
        raise ResultError(f"{engine}.runs must contain exactly 12 entries")
    expected_pairs = {(scene, iteration) for scene in SCENES for iteration in (1, 2)}
    observed_pairs: set[tuple[str, int]] = set()
    successful_durations: list[float] = []
    successful_runs = 0
    for index, run in enumerate(runs):
        location = f"{engine}.runs[{index}]"
        if not isinstance(run, dict):
            raise ResultError(f"{location} must be an object")
        pair = (run.get("scene_id"), run.get("iteration"))
        if pair not in expected_pairs or pair in observed_pairs:
            raise ResultError(f"{location} has an invalid or duplicate scene iteration")
        observed_pairs.add(pair)
        success = run.get("success")
        exit_code = run.get("exit_code")
        duration = run.get("duration_seconds")
        if not isinstance(success, bool):
            raise ResultError(f"{location}.success must be boolean")
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            raise ResultError(f"{location}.exit_code must be an integer")
        if isinstance(duration, bool) or not isinstance(duration, int | float) or duration <= 0:
            raise ResultError(f"{location}.duration_seconds must be positive")
        _non_empty_string(run.get("command"), f"{location}.command")
        _non_empty_string(run.get("log_path"), f"{location}.log_path")
        if success:
            if exit_code != 0:
                raise ResultError(f"{location} cannot succeed with a non-zero exit code")
            _non_empty_string(run.get("output_path"), f"{location}.output_path")
            output_hash = _non_empty_string(
                run.get("output_sha256"), f"{location}.output_sha256"
            )
            if len(output_hash) != 64 or any(
                char not in "0123456789abcdef" for char in output_hash
            ):
                raise ResultError(f"{location}.output_sha256 must be lowercase SHA-256")
            successful_runs += 1
            successful_durations.append(float(duration))
        elif exit_code == 0:
            raise ResultError(f"{location} cannot fail with a zero exit code")

    if observed_pairs != expected_pairs:
        raise ResultError(f"{engine}.runs does not cover every scene twice")

    capabilities = raw.get("capabilities")
    if not isinstance(capabilities, dict) or set(capabilities) != set(CAPABILITIES):
        raise ResultError(f"{engine}.capabilities must contain the three scoring dimensions")
    capability_scores: dict[str, float] = {}
    for name in CAPABILITIES:
        item = capabilities[name]
        if not isinstance(item, dict) or set(item) != {"score", "evidence"}:
            raise ResultError(f"{engine}.capabilities.{name} has invalid fields")
        capability_scores[name] = _bounded_score(item["score"], f"{engine}.{name}")
        _non_empty_string(item["evidence"], f"{engine}.{name}.evidence")

    return ValidatedResult(
        engine=engine,
        successful_runs=successful_runs,
        mean_duration=mean(successful_durations) if successful_durations else None,
        first_attempt_score=sum(attempts.values()) / len(SCENES) * 100,
        visual_score=capability_scores["visual_score"],
        sections_cache_score=capability_scores["sections_cache_score"],
        deployment_score=capability_scores["deployment_score"],
    )


def score_results(first: Any, second: Any) -> dict[str, Any]:
    validated = [validate_result(first), validate_result(second)]
    if {item.engine for item in validated} != ENGINES:
        raise ResultError("one result for manimce and one for manimgl are required")

    qualified = [item for item in validated if item.successful_runs == 12]
    fastest = min(item.mean_duration for item in qualified) if qualified else None
    engines: dict[str, dict[str, Any]] = {}
    for item in validated:
        is_qualified = item.successful_runs == 12
        speed_score = (
            fastest / item.mean_duration * 100
            if is_qualified and fastest is not None and item.mean_duration is not None
            else 0.0
        )
        dimensions = {
            "stability": item.successful_runs / 12 * 100,
            "speed": speed_score,
            "first_attempt": item.first_attempt_score,
            "visual": item.visual_score,
            "sections_cache": item.sections_cache_score,
            "deployment": item.deployment_score,
        }
        total = sum(dimensions[name] * WEIGHTS[name] for name in WEIGHTS)
        engines[item.engine] = {
            "qualified": is_qualified,
            "successful_runs": item.successful_runs,
            "mean_duration_seconds": item.mean_duration,
            "dimensions": {name: round(value, 3) for name, value in dimensions.items()},
            "total_score": round(total, 3),
        }

    if not qualified:
        selection = None
    elif len(qualified) == 1:
        selection = qualified[0].engine
    else:
        ce_score = engines["manimce"]["total_score"]
        gl_score = engines["manimgl"]["total_score"]
        selection = "manimce" if abs(ce_score - gl_score) <= 10 else max(
            ENGINES, key=lambda engine: engines[engine]["total_score"]
        )
    return {"selection": selection, "engines": engines, "weights": WEIGHTS}


def main() -> int:
    parser = argparse.ArgumentParser(description="Score Phase 2 Manim engine results")
    parser.add_argument("manimce", type=Path)
    parser.add_argument("manimgl", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = score_results(
            json.loads(args.manimce.read_text(encoding="utf-8")),
            json.loads(args.manimgl.read_text(encoding="utf-8")),
        )
    except (OSError, json.JSONDecodeError, ResultError) as error:
        print(f"INVALID: {error}")
        return 1
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
