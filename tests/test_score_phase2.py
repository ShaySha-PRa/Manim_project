from __future__ import annotations

import unittest

from scripts.score_phase2 import ResultError, score_results

SCENES = (
    "formula_transform",
    "derivative",
    "function_plot",
    "parameter_sweep",
    "tangent",
    "area",
)


def engine_result(engine: str, *, duration: float, successes: int = 12) -> dict:
    runs = []
    run_number = 0
    for scene in SCENES:
        for iteration in (1, 2):
            run_number += 1
            success = run_number <= successes
            runs.append(
                {
                    "scene_id": scene,
                    "iteration": iteration,
                    "success": success,
                    "exit_code": 0 if success else 1,
                    "duration_seconds": duration,
                    "command": "render command",
                    "output_path": "artifacts/out.mp4" if success else "",
                    "output_sha256": "a" * 64 if success else "",
                    "log_path": "artifacts/run.log",
                }
            )
    return {
        "engine": engine,
        "engine_version": "1.0",
        "python_version": "3.12",
        "ffmpeg_version": "7.0",
        "latex_version": "TeX Live",
        "font_versions": ["DejaVu Sans"],
        "container_or_environment": "immutable-test-env",
        "first_attempt_success": {scene: True for scene in SCENES},
        "runs": runs,
        "capabilities": {
            "visual_score": {"score": 90, "evidence": "six scenes inspected"},
            "sections_cache_score": {"score": 80, "evidence": "feature exercised"},
            "deployment_score": {"score": 70, "evidence": "environment reproduced"},
        },
        "notes": [],
    }


class Phase2ScoringTests(unittest.TestCase):
    def test_selects_ce_when_scores_are_within_ten_points(self) -> None:
        report = score_results(
            engine_result("manimce", duration=11),
            engine_result("manimgl", duration=10),
        )
        self.assertEqual(report["selection"], "manimce")
        self.assertTrue(report["engines"]["manimce"]["qualified"])

    def test_disqualifies_engine_with_any_failed_run(self) -> None:
        report = score_results(
            engine_result("manimce", duration=10, successes=11),
            engine_result("manimgl", duration=20),
        )
        self.assertEqual(report["selection"], "manimgl")
        self.assertFalse(report["engines"]["manimce"]["qualified"])

    def test_selects_nothing_when_both_engines_fail(self) -> None:
        report = score_results(
            engine_result("manimce", duration=10, successes=11),
            engine_result("manimgl", duration=10, successes=11),
        )
        self.assertIsNone(report["selection"])

    def test_rejects_missing_scene_iteration(self) -> None:
        ce = engine_result("manimce", duration=10)
        ce["runs"].pop()
        with self.assertRaisesRegex(ResultError, "exactly 12"):
            score_results(ce, engine_result("manimgl", duration=10))


if __name__ == "__main__":
    unittest.main()
