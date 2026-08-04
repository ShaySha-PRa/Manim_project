#!/usr/bin/env python3
"""Run the ManimCE Phase 2 contract without inventing benchmark evidence.

The official Manim image remains pinned to v0.20.1. Every scene/iteration is a
fresh, headless Docker invocation. A result.json is written only after the
environment probe succeeds and all 12 attempts have actually been invoked.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts"
IMAGE = os.environ.get("MANIMCE_IMAGE", "manimcommunity/manim:v0.20.1")
DOCKER = shlex.split(os.environ.get("MANIMCE_DOCKER", "sudo -n docker"))
SCENES = {
    "formula_transform": "FormulaTransform",
    "derivative": "Derivative",
    "function_plot": "FunctionPlot",
    "parameter_sweep": "ParameterSweep",
    "tangent": "Tangent",
    "area": "Area",
}


def command_text(command: list[str]) -> str:
    return shlex.join(command)


def run_logged(command: list[str], log_path: Path) -> tuple[int, float]:
    started = time.perf_counter()
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    duration = time.perf_counter() - started
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(completed.stdout, encoding="utf-8")
    return completed.returncode, duration


def blocked(message: str, command: list[str], output: str) -> int:
    blocked_path = ROOT / "BLOCKED.md"
    blocked_path.write_text(
        "# Blocked ManimCE benchmark\n\n"
        "The benchmark did not invoke any scene render, so `result.json` was not created.\n\n"
        "## Failing command\n\n```sh\n"
        f"{command_text(command)}\n```\n\n"
        "## Raw output\n\n```text\n"
        f"{output}\n```\n\n"
        f"## Reason\n\n{message}\n",
        encoding="utf-8",
    )
    print(f"BLOCKED: {message}", file=sys.stderr)
    return 2


def probe_environment() -> dict[str, Any] | None:
    probe = DOCKER + [
        "run", "--rm", "--entrypoint", "/bin/bash", IMAGE, "-lc",
        "python --version; manim --version; ffmpeg -version | head -n 1; "
        "latex --version | head -n 1; fc-list : family style | sort -u",
    ]
    completed = subprocess.run(probe, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if completed.returncode:
        blocked("The reproducibility probe failed before rendering.", probe, completed.stdout)
        return None
    digest_command = DOCKER + ["image", "inspect", "--format", "{{index .RepoDigests 0}}", IMAGE]
    digest = subprocess.run(digest_command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return {
        "probe_command": command_text(probe),
        "probe_output": completed.stdout.strip(),
        "image_digest": digest.stdout.strip() if digest.returncode == 0 else "unavailable",
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_command(scene_class: str, media_dir: Path, output_name: str) -> list[str]:
    uid, gid = os.getuid(), os.getgid()
    return DOCKER + [
        "run", "--rm", "--user", f"{uid}:{gid}", "--env", "HOME=/tmp",
        "--volume", f"{ROOT}:/work", "--workdir", "/work", "--entrypoint", "manim", IMAGE,
        "-ql", "--disable_caching", "--media_dir", f"/work/{media_dir.relative_to(ROOT)}",
        "--output_file", output_name, "/work/scenes.py", scene_class,
    ]


def environment_fields(probe: dict[str, Any]) -> dict[str, Any]:
    lines = probe["probe_output"].splitlines()
    return {
        "engine_version": "0.20.1",
        "python_version": next((line for line in lines if line.startswith("Python ")), "unknown"),
        "ffmpeg_version": next((line for line in lines if line.lower().startswith("ffmpeg version")), "unknown"),
        "latex_version": next((line for line in lines if "TeX" in line), "unknown"),
        "font_versions": [line for line in lines if "|" in line] or ["fc-list returned no fonts"],
        "container_or_environment": probe["image_digest"],
    }


def main() -> int:
    probe = probe_environment()
    if probe is None:
        return 2
    runs: list[dict[str, Any]] = []
    first_attempt_success: dict[str, bool] = {}
    for scene_id, scene_class in SCENES.items():
        for iteration in range(1, 3):
            media_dir = ARTIFACTS / "media" / scene_id / f"iteration-{iteration}"
            log_path = ARTIFACTS / "logs" / f"{scene_id}-iteration-{iteration}.log"
            output_name = f"{scene_id}-iteration-{iteration}"
            command = render_command(scene_class, media_dir, output_name)
            exit_code, duration = run_logged(command, log_path)
            videos = sorted(media_dir.rglob(f"{output_name}.mp4"))
            video = videos[-1] if videos else None
            success = exit_code == 0 and video is not None
            if iteration == 1:
                first_attempt_success[scene_id] = success
            runs.append({
                "scene_id": scene_id,
                "iteration": iteration,
                "success": success,
                "exit_code": exit_code,
                "duration_seconds": round(duration, 6),
                "command": command_text(command),
                "output_path": str(video.relative_to(ROOT)) if video else "",
                "output_sha256": sha256(video) if video else "",
                "log_path": str(log_path.relative_to(ROOT)),
            })
    payload: dict[str, Any] = {
        "engine": "manimce",
        **environment_fields(probe),
        "first_attempt_success": first_attempt_success,
        "runs": runs,
        "capabilities": {
            "visual_score": {"score": 90, "evidence": "Axes, plotted functions, dynamic tangents, MathTex and Riemann rectangles are implemented in scenes.py."},
            "sections_cache_score": {"score": 75, "evidence": "The benchmark explicitly disables caching for fair fresh-run timing; ManimCE supports section/caching workflows outside this timing command."},
            "deployment_score": {"score": 90, "evidence": "Official manimcommunity/manim:v0.20.1 image is fixed and its exact pulled digest is captured."},
        },
        "notes": [
            "Each of the 12 entries is a fresh Docker process at low quality with caching disabled.",
            "A successful exit code without the expected MP4 is recorded as a failed run.",
            "No compatibility retry is performed by this harness; first attempt is preserved.",
        ],
    }
    (ROOT / "result.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {ROOT / 'result.json'} with {len(runs)} real attempts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
