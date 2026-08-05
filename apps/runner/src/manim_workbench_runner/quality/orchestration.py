from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path

from manim_workbench_contracts import RenderArtifactPayload

from .visual import MediaAnalysisError, PyAVVideoReader, VisualDiagnosticAnalyzer, VisualLimits
from .visual.reader import VideoReader

_MAX_METADATA_BYTES = 256 * 1024


def analyze_published_video(
    *,
    artifact_directory: Path,
    target_duration_seconds: float,
    artifacts: tuple[RenderArtifactPayload, ...],
    reader: VideoReader | None = None,
) -> tuple[RenderArtifactPayload, ...]:
    """Append deterministic, redacted evidence and refresh the metadata artifact digest."""
    metadata_path = artifact_directory / "metadata.json"
    if metadata_path.is_symlink() or metadata_path.stat().st_size > _MAX_METADATA_BYTES:
        raise MediaAnalysisError("unsafe_metadata")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}

    video_reader = reader or PyAVVideoReader()
    try:
        probe = video_reader.probe(artifact_directory, Path("video.mp4"))
        limits = (
            VisualLimits(sample_count=12, max_analysis_seconds=60)
            if probe.width * probe.height > 1_000_000
            else VisualLimits(max_analysis_seconds=30)
        )
        result = VisualDiagnosticAnalyzer(reader=video_reader, limits=limits).analyze(
            media_root=artifact_directory,
            relative_media_path=Path("video.mp4"),
            target_duration_seconds=target_duration_seconds,
        )
        quality = {
            "diagnostics": [
                {
                    "code": item.code,
                    "measured_value": item.measured_value,
                    "severity": item.severity,
                    "summary": item.summary,
                    "threshold_value": item.threshold_value,
                }
                for item in result.diagnostics
            ],
            "policy_version": "phase9-visual-v1",
            "sampled_frame_indices": list(result.sampled_frame_indices),
            "signature": result.signature,
            "target_duration_seconds": target_duration_seconds,
            "video": {
                "duration_seconds": probe.duration_seconds,
                "fps": probe.fps,
                "frame_count": probe.frame_count,
                "height": probe.height,
                "width": probe.width,
            },
        }
    except MediaAnalysisError:
        quality = {
            "diagnostics": [
                {
                    "code": "media_metadata_invalid",
                    "measured_value": None,
                    "severity": "error",
                    "summary": "Rendered media metadata could not be verified.",
                    "threshold_value": None,
                }
            ],
            "policy_version": "phase9-visual-v1",
            "sampled_frame_indices": [],
            "signature": sha256(b"media_metadata_invalid").hexdigest(),
            "target_duration_seconds": target_duration_seconds,
            "video": None,
        }
    metadata["quality"] = quality
    encoded = (json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    if len(encoded) > _MAX_METADATA_BYTES:
        raise MediaAnalysisError("metadata_size_limit")
    temporary = artifact_directory / ".metadata.phase9.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(metadata_path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise

    digest = sha256(encoded).hexdigest()
    return tuple(
        artifact.model_copy(update={"sha256": digest, "byte_size": len(encoded)})
        if artifact.kind.value == "metadata"
        else artifact
        for artifact in artifacts
    )
