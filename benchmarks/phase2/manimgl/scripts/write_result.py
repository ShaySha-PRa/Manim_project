#!/usr/bin/env python3
"""Create result.json only from twelve measured render records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

SCENES = (
    "formula_transform",
    "derivative",
    "function_plot",
    "parameter_sweep",
    "tangent",
    "area",
)


def write_result(root: Path) -> None:
    artifacts = root / "artifacts"
    runs = [
        json.loads(line)
        for line in (artifacts / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    expected = {(scene, iteration) for scene in SCENES for iteration in (1, 2)}
    actual = {(run["scene_id"], run["iteration"]) for run in runs}
    if len(runs) != 12 or actual != expected:
        raise SystemExit("result.json refused: exactly 12 measured scene iterations are required")

    environment = json.loads((artifacts / "environment.json").read_text(encoding="utf-8"))
    first_attempt = {
        scene: next(
            run["success"]
            for run in runs
            if run["scene_id"] == scene and run["iteration"] == 1
        )
        for scene in SCENES
    }
    result = {
        "engine": "manimgl",
        "engine_version": environment["engine_version"],
        "python_version": environment["python_version"],
        "ffmpeg_version": environment["ffmpeg_version"],
        "latex_version": environment["latex_version"],
        "font_versions": environment["font_versions"],
        "container_or_environment": environment["container_or_environment"],
        "first_attempt_success": first_attempt,
        "runs": runs,
        "capabilities": {
            "visual_score": {
                "score": 0,
                "evidence": "Deferred to parent visual sampling of all six output types.",
            },
            "sections_cache_score": {
                "score": 0,
                "evidence": "No automatic sections/cache claim is made by this runner.",
            },
            "deployment_score": {
                "score": 0,
                "evidence": "Deferred to parent comparison using image ID and build evidence.",
            },
        },
        "notes": [
            "Runs use Xvfb and Mesa llvmpipe in a fresh container invocation.",
            "Capability scores are intentionally unassessed pending parent review.",
        ],
    }
    (root / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    write_result(args.root.resolve())


if __name__ == "__main__":
    main()
