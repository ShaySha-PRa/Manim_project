#!/usr/bin/env python3
"""Run the fixed, resumable 48-attempt Phase 4 render acceptance matrix."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from manim_workbench_runner.rendering import (
    MANIM_IMAGE,
    MANIM_IMAGE_DIGEST,
    MANIM_VERSION,
    CommandRunner,
    RenderEngine,
    RenderFailureResult,
    RenderProfile,
    RenderRequest,
    RenderSuccess,
    SubprocessCommandRunner,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = (
    Path("reference_scenes/formula/manifest.py"),
    Path("reference_scenes/functions/manifest.py"),
)
RECORD_TYPE = "phase4-render-attempt"
ENVIRONMENT_PROBE_SCRIPT = """
import json
import platform
import subprocess

import av
import manim

def first_line(command):
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if completed.returncode != 0:
        raise RuntimeError(f"{command[0]} probe failed with {completed.returncode}")
    return completed.stdout.splitlines()[0]

fonts = []
for family in ("sans-serif", "serif", "monospace"):
    completed = subprocess.run(
        ["fc-match", "-f", "%{family} %{style}", family],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"fc-match probe failed with {completed.returncode}")
    fonts.append(completed.stdout.strip())

print(json.dumps({
    "python_version": platform.python_version(),
    "manim_version": manim.__version__,
    "pyav_version": av.__version__,
    "ffmpeg_libraries": {name: list(version) for name, version in av.library_versions.items()},
    "latex_version": first_line(["latex", "--version"]),
    "fonts": fonts,
}, sort_keys=True))
""".strip()


@dataclass(frozen=True, slots=True)
class SceneSpec:
    scene_id: str
    scene_class: str
    source_path: Path
    category: str


@dataclass(frozen=True, slots=True)
class AcceptanceAttempt:
    scene: SceneSpec
    profile: str
    iteration: int

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.scene.scene_id, self.profile, self.iteration)

    @property
    def slug(self) -> str:
        return f"{self.scene.scene_id}-{self.profile}-{self.iteration}"


def _safe_relative_path(value: Path, label: str) -> Path:
    posix = PurePosixPath(value.as_posix())
    if value.is_absolute() or not posix.parts or ".." in posix.parts:
        raise ValueError(f"{label} must be a safe relative path")
    return value


def safe_artifact_root(project_root: Path, requested: Path) -> Path:
    """Resolve and create a user-selected root without escaping the project."""

    relative = _safe_relative_path(requested, "artifact root")
    resolved_project = project_root.resolve()
    resolved = (resolved_project / relative).resolve()
    if not resolved.is_relative_to(resolved_project):
        raise ValueError("artifact root must stay inside project root")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def load_scenes(project_root: Path = PROJECT_ROOT) -> list[SceneSpec]:
    """Load exactly the two versioned manifests, six entries from each."""

    scenes: list[SceneSpec] = []
    for manifest_path in MANIFESTS:
        namespace = runpy.run_path(str(project_root / manifest_path))
        entries = namespace.get("SCENE_MANIFEST")
        if not isinstance(entries, tuple) or len(entries) != 6:
            raise ValueError(f"{manifest_path} must contain exactly six SCENE_MANIFEST entries")
        for raw in entries:
            if not isinstance(raw, dict):
                raise ValueError(f"{manifest_path} contains a non-object entry")
            try:
                source_path = _safe_relative_path(Path(raw["source_path"]), "source path")
                scene = SceneSpec(
                    scene_id=str(raw["scene_id"]),
                    scene_class=str(raw["scene_class"]),
                    source_path=source_path,
                    category=str(raw["category"]),
                )
            except KeyError as exc:
                raise ValueError(f"{manifest_path} entry is missing {exc.args[0]}") from exc
            scenes.append(scene)
    if len(scenes) != 12 or len({scene.scene_id for scene in scenes}) != 12:
        raise ValueError("the two manifests must define exactly 12 unique scene IDs")
    if any(not (project_root / scene.source_path).is_file() for scene in scenes):
        raise ValueError("every manifest source_path must identify an existing Scene file")
    return scenes


def build_matrix(scenes: list[SceneSpec]) -> list[AcceptanceAttempt]:
    if len(scenes) != 12 or len({scene.scene_id for scene in scenes}) != 12:
        raise ValueError("acceptance requires exactly 12 unique scenes")
    return [
        AcceptanceAttempt(scene, profile, iteration)
        for scene in scenes
        for profile, iterations in (("preview", range(1, 4)), ("final", range(1, 2)))
        for iteration in iterations
    ]


def append_jsonl(path: Path, record: dict[str, object]) -> None:
    """Durably append one complete JSON object without rewriting prior evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def probe_environment(command_runner: CommandRunner | None = None) -> dict[str, object]:
    runner = command_runner or SubprocessCommandRunner()
    command = [
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "python",
        MANIM_IMAGE,
        "-c",
        ENVIRONMENT_PROBE_SCRIPT,
    ]
    result = runner.run(command, timeout_seconds=30)
    if result.returncode != 0:
        raise RuntimeError(f"environment probe failed with {result.returncode}: {result.output}")
    try:
        payload = json.loads(result.output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("environment probe returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("environment probe returned a non-object")
    if payload.get("manim_version") != MANIM_VERSION:
        raise RuntimeError("environment probe returned the wrong Manim version")
    return {
        "image": MANIM_IMAGE,
        "image_digest": MANIM_IMAGE_DIGEST,
        **payload,
    }


def preserve_environment(path: Path, environment: dict[str, object]) -> None:
    rendered = json.dumps(environment, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise RuntimeError("acceptance environment changed since the previous attempt")
        return
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(rendered)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _record_key(record: dict[str, Any]) -> tuple[str, str, int]:
    try:
        scene_id = record["scene_id"]
        profile = record["profile"]
        iteration = record["iteration"]
    except KeyError as exc:
        raise ValueError(f"runs.jsonl record is missing {exc.args[0]}") from exc
    if not isinstance(scene_id, str) or profile not in {"preview", "final"}:
        raise ValueError("runs.jsonl record has an invalid scene/profile key")
    if not isinstance(iteration, int):
        raise ValueError("runs.jsonl iteration must be an integer")
    return scene_id, profile, iteration


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_number}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"non-object JSON at {path}:{line_number}")
            records.append(record)
    return records


def completed_attempts(path: Path) -> set[tuple[str, str, int]]:
    """Skip keys whose latest durable attempt succeeded."""

    latest_success: dict[tuple[str, str, int], bool] = {}
    for record in read_jsonl(path):
        key = _record_key(record)
        latest_success[key] = record.get("success") is True
    return {key for key, succeeded in latest_success.items() if succeeded}


def _artifact_payload(result: RenderSuccess) -> dict[str, dict[str, object]]:
    return {
        name: {
            "relative_path": info.relative_path,
            "byte_size": info.byte_size,
            "sha256": info.sha256,
        }
        for name, info in result.artifacts.items()
    }


def _success_record(
    attempt: AcceptanceAttempt,
    result: RenderSuccess,
    *,
    started_at: str,
    finished_at: str,
    wall_seconds: float,
) -> dict[str, object]:
    metadata = result.metadata
    video_metadata = metadata.get("video")
    if not isinstance(video_metadata, dict):
        raise ValueError("successful RenderResult is missing video metadata")
    video_artifact = result.artifacts.get("video")
    if video_artifact is None:
        raise ValueError("successful RenderResult is missing the video artifact")
    return {
        "record_type": RECORD_TYPE,
        "scene_id": attempt.scene.scene_id,
        "scene_class": attempt.scene.scene_class,
        "source_path": attempt.scene.source_path.as_posix(),
        "category": attempt.scene.category,
        "profile": attempt.profile,
        "iteration": attempt.iteration,
        "success": True,
        "cache_hit": result.cache_hit,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(wall_seconds, 6),
        "wall_seconds": round(wall_seconds, 6),
        "render_seconds": metadata.get("render_seconds"),
        "cache_key": result.cache_key,
        "video": {**video_metadata, "sha256": video_artifact.sha256},
        "artifacts": _artifact_payload(result),
    }


def _failure_record(
    attempt: AcceptanceAttempt,
    result: RenderFailureResult,
    *,
    started_at: str,
    finished_at: str,
    wall_seconds: float,
) -> dict[str, object]:
    return {
        "record_type": RECORD_TYPE,
        "scene_id": attempt.scene.scene_id,
        "scene_class": attempt.scene.scene_class,
        "source_path": attempt.scene.source_path.as_posix(),
        "category": attempt.scene.category,
        "profile": attempt.profile,
        "iteration": attempt.iteration,
        "success": False,
        "cache_hit": False,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(wall_seconds, 6),
        "wall_seconds": round(wall_seconds, 6),
        "render_seconds": None,
        "video": None,
        "artifacts": {},
        "failure": {
            "code": result.code.value,
            "stage": result.stage.value,
            "message": result.message,
            "exit_code": result.exit_code,
            "log_relative_path": result.log_relative_path,
        },
    }


def run_attempt(
    engine: RenderEngine,
    attempt: AcceptanceAttempt,
    artifact_root: Path,
) -> dict[str, object]:
    attempt_root = artifact_root / "attempts" / attempt.slug
    request = RenderRequest(
        scene_id=attempt.scene.scene_id,
        scene_class=attempt.scene.scene_class,
        source_path=attempt.scene.source_path,
        profile=RenderProfile(attempt.profile),
        artifact_root=attempt_root,
    )
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    result = engine.render(request, use_cache=False, disable_manim_cache=True)
    wall_seconds = time.perf_counter() - started
    finished_at = datetime.now(timezone.utc).isoformat()
    if isinstance(result, RenderSuccess):
        return _success_record(
            attempt,
            result,
            started_at=started_at,
            finished_at=finished_at,
            wall_seconds=wall_seconds,
        )
    return _failure_record(
        attempt,
        result,
        started_at=started_at,
        finished_at=finished_at,
        wall_seconds=wall_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("runtime/phase4-acceptance"),
        help="safe path relative to the project root",
    )
    args = parser.parse_args(argv)
    artifact_root_absolute = safe_artifact_root(PROJECT_ROOT, args.artifact_root)
    artifact_root_relative = artifact_root_absolute.relative_to(PROJECT_ROOT)
    runs_path = artifact_root_absolute / "runs.jsonl"
    preserve_environment(artifact_root_absolute / "environment.json", probe_environment())
    matrix = build_matrix(load_scenes())
    completed = completed_attempts(runs_path)
    engine = RenderEngine(project_root=PROJECT_ROOT)
    failures = 0
    for attempt in matrix:
        if attempt.key in completed:
            continue
        record = run_attempt(engine, attempt, artifact_root_relative)
        append_jsonl(runs_path, record)
        failures += int(record["success"] is not True)
        print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
