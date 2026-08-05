from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from manim_workbench_contracts import RenderArtifactPayload
from manim_workbench_runner.quality.orchestration import analyze_published_video
from manim_workbench_runner.quality.visual import FrameSample, MediaMetadata


class Reader:
    def probe(self, _root: Path, _relative: Path) -> MediaMetadata:
        return MediaMetadata(16, 2, 2, 2, 90.0, 30.0)

    def read_frames(self, _root: Path, _relative: Path, indices: tuple[int, ...]):
        pixels = bytes((0, 0, 0) * 4)
        return tuple(FrameSample(index, float(index), 2, 2, pixels) for index in indices)


def test_runner_embeds_quality_evidence_and_refreshes_metadata_digest(tmp_path: Path) -> None:
    (tmp_path / "video.mp4").write_bytes(b"not-read-by-fake")
    (tmp_path / "metadata.json").write_text('{"profile":"preview"}\n', encoding="utf-8")
    artifacts = (
        RenderArtifactPayload(
            kind="metadata", relative_path="metadata.json", sha256="0" * 64, byte_size=1
        ),
    )

    updated = analyze_published_video(
        artifact_directory=tmp_path,
        target_duration_seconds=90,
        artifacts=artifacts,
        reader=Reader(),
    )

    encoded = (tmp_path / "metadata.json").read_bytes()
    payload = json.loads(encoded)
    assert payload["quality"]["video"]["duration_seconds"] == 90
    assert payload["quality"]["target_duration_seconds"] == 90
    assert updated[0].sha256 == sha256(encoded).hexdigest()
    assert updated[0].byte_size == len(encoded)
