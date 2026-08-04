"""Contract tests for Agent C's resumable Phase 4 acceptance tools."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def load_tool(name: str):
    path = PROJECT_ROOT / "benchmarks" / "phase4" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"phase4_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def scene_specs(tool: object) -> list[object]:
    scene_spec = tool.SceneSpec
    return [
        scene_spec(
            scene_id=f"scene_{index}",
            scene_class=f"Scene{index}",
            source_path=Path(f"reference_scenes/formula/scene_{index}.py"),
            category="formula",
        )
        for index in range(1, 13)
    ]


def test_acceptance_matrix_is_fixed_to_36_preview_plus_12_final() -> None:
    tool = load_tool("run_acceptance")

    matrix = tool.build_matrix(scene_specs(tool))

    assert len(matrix) == 48
    assert sum(item.profile == "preview" for item in matrix) == 36
    assert sum(item.profile == "final" for item in matrix) == 12
    assert {(item.scene.scene_id, item.profile, item.iteration) for item in matrix} == {
        (f"scene_{index}", profile, iteration)
        for index in range(1, 13)
        for profile, iterations in (("preview", range(1, 4)), ("final", range(1, 2)))
        for iteration in iterations
    }


def test_resume_records_append_without_overwriting_or_duplicate_schedule(tmp_path: Path) -> None:
    tool = load_tool("run_acceptance")
    root = tool.safe_artifact_root(tmp_path, Path("runtime/phase4-acceptance"))
    runs_path = root / "runs.jsonl"
    record = {"scene_id": "scene_1", "profile": "preview", "iteration": 1, "success": True}

    tool.append_jsonl(runs_path, record)
    tool.append_jsonl(runs_path, {**record, "scene_id": "scene_2"})
    tool.append_jsonl(runs_path, record)
    tool.append_jsonl(runs_path, {**record, "scene_id": "scene_2", "success": False})

    completed = tool.completed_attempts(runs_path)
    assert completed == {("scene_1", "preview", 1)}
    assert runs_path.read_text(encoding="utf-8").count("\n") == 4
    with pytest.raises(ValueError):
        tool.safe_artifact_root(tmp_path, Path("../escape"))
    with pytest.raises(ValueError):
        tool.safe_artifact_root(tmp_path, tmp_path / "absolute")


def make_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for scene_index in range(1, 13):
        for profile, iterations in (("preview", range(1, 4)), ("final", range(1, 2))):
            for iteration in iterations:
                records.append(
                    {
                        "record_type": "phase4-render-attempt",
                        "scene_id": f"scene_{scene_index}",
                        "profile": profile,
                        "iteration": iteration,
                        "success": True,
                        "cache_hit": False,
                        "duration_seconds": 5.0 if profile == "preview" else 20.0,
                        "video": {
                            "duration_seconds": 4.0,
                            "frame_count": 60,
                            "width": 854 if profile == "preview" else 1920,
                            "height": 480 if profile == "preview" else 1080,
                            "fps": 15.0 if profile == "preview" else 60.0,
                            "sha256": f"hash-{scene_index}-{profile}-{iteration}",
                        },
                    }
                )
    return records


def test_summary_accepts_hash_differences_when_stream_properties_match() -> None:
    tool = load_tool("summarize")

    report = tool.summarize_records(make_records())

    assert report["gate_passed"] is True
    assert report["success_rate"] == 1.0
    assert report["preview_median_seconds"] == 5.0
    assert len(report["hash_differences"]) == 12
    with pytest.raises(ValueError, match="48"):
        tool.summarize_records(make_records()[:-1])
