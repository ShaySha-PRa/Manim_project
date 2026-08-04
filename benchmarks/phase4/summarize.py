#!/usr/bin/env python3
"""Validate and summarize Phase 4's effective 48-render acceptance evidence."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

STREAM_PROPERTIES = ("duration_seconds", "frame_count", "width", "height", "fps")


def read_records(path: Path) -> list[dict[str, Any]]:
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


def _key(record: dict[str, Any]) -> tuple[str, str, int]:
    try:
        scene_id = record["scene_id"]
        profile = record["profile"]
        iteration = record["iteration"]
    except KeyError as exc:
        raise ValueError(f"record is missing {exc.args[0]}") from exc
    if not isinstance(scene_id, str) or not scene_id:
        raise ValueError("scene_id must be a non-empty string")
    if profile not in {"preview", "final"}:
        raise ValueError("profile must be preview or final")
    if not isinstance(iteration, int):
        raise ValueError("iteration must be an integer")
    return scene_id, profile, iteration


def _effective_records(records: list[dict[str, Any]]) -> dict[tuple[str, str, int], dict[str, Any]]:
    """Use the last appended retry for each key while preserving append-only evidence."""

    latest: dict[tuple[str, str, int], dict[str, Any]] = {}
    for record in records:
        latest[_key(record)] = record
    return latest


def _expected_keys(scene_ids: set[str]) -> set[tuple[str, str, int]]:
    return {
        (scene_id, profile, iteration)
        for scene_id in scene_ids
        for profile, iterations in (("preview", range(1, 4)), ("final", range(1, 2)))
        for iteration in iterations
    }


def _video(record: dict[str, Any]) -> dict[str, Any] | None:
    video = record.get("video")
    return video if isinstance(video, dict) else None


def summarize_records(records: list[dict[str, Any]]) -> dict[str, object]:
    effective = _effective_records(records)
    scene_ids = {key[0] for key in effective}
    expected = _expected_keys(scene_ids)
    if len(scene_ids) != 12 or len(effective) != 48 or set(effective) != expected:
        raise ValueError("acceptance evidence must contain exactly 48 expected unique keys")

    ordered = [effective[key] for key in sorted(effective)]
    successes = [record for record in ordered if record.get("success") is True]
    preview_durations = [
        float(record["duration_seconds"])
        for record in ordered
        if record["profile"] == "preview"
        and isinstance(record.get("duration_seconds"), int | float)
    ]

    stream_mismatches: list[dict[str, object]] = []
    hash_differences: list[dict[str, object]] = []
    for scene_id in sorted(scene_ids):
        for profile in ("preview", "final"):
            group = [
                effective[key]
                for key in sorted(effective)
                if key[0] == scene_id and key[1] == profile
            ]
            videos = [_video(record) for record in group]
            if any(video is None for video in videos):
                stream_mismatches.append(
                    {"scene_id": scene_id, "profile": profile, "reason": "missing video metadata"}
                )
                continue
            concrete_videos = [video for video in videos if video is not None]
            differing_properties = {
                property_name: [video.get(property_name) for video in concrete_videos]
                for property_name in STREAM_PROPERTIES
                if len({video.get(property_name) for video in concrete_videos}) != 1
            }
            if differing_properties:
                stream_mismatches.append(
                    {
                        "scene_id": scene_id,
                        "profile": profile,
                        "properties": differing_properties,
                    }
                )
            hashes = [video.get("sha256") for video in concrete_videos]
            if len(set(hashes)) > 1:
                hash_differences.append(
                    {"scene_id": scene_id, "profile": profile, "sha256": hashes}
                )

    preview_median = statistics.median(preview_durations) if preview_durations else None
    gate_failures: list[str] = []
    if len(successes) != 48:
        gate_failures.append(f"only {len(successes)}/48 effective attempts succeeded")
    if len(preview_durations) != 36:
        gate_failures.append("preview timing evidence must contain exactly 36 numeric values")
    elif preview_median is None or preview_median > 60:
        gate_failures.append(f"preview median {preview_median} exceeds 60 seconds")
    if stream_mismatches:
        gate_failures.append("observable video stream properties are not repeatable")

    return {
        "record_count": len(records),
        "effective_record_count": len(effective),
        "expected_unique_key_count": len(expected),
        "scene_count": len(scene_ids),
        "success_count": len(successes),
        "success_rate": len(successes) / 48,
        "preview_count": len(preview_durations),
        "preview_median_seconds": preview_median,
        "repeatable_stream_properties": not stream_mismatches,
        "stream_mismatches": stream_mismatches,
        "hash_differences": hash_differences,
        "gate_failures": gate_failures,
        "gate_passed": not gate_failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs_jsonl", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = summarize_records(read_records(args.runs_jsonl))
    except (OSError, ValueError) as exc:
        report = {"gate_passed": False, "gate_failures": [str(exc)]}
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0 if report["gate_passed"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
