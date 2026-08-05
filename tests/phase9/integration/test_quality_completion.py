from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from manim_workbench_api.quality.completion import record_completed_quality
from manim_workbench_api.quality.reports import QualityReportRepository, QualityReportService
from manim_workbench_contracts import RenderArtifactPayload, RenderJobCompletion

from tests.phase9.reports.test_quality_report_service import (
    JOB_A,
    OWNER_A,
    migrated_engine,
)


def test_completed_render_creates_an_owner_scoped_report_from_runner_evidence(
    tmp_path: Path,
) -> None:
    engine = migrated_engine(tmp_path)
    root = tmp_path / "artifacts"
    directory = root / str(JOB_A) / "attempt-1"
    directory.mkdir(parents=True)
    metadata = {
        "quality": {
            "policy_version": "phase9-visual-v1",
            "target_duration_seconds": 90,
            "signature": "0" * 64,
            "sampled_frame_indices": [0, 10],
            "video": {"duration_seconds": 9.6, "fps": 30, "frame_count": 288},
            "diagnostics": [],
        }
    }
    encoded = (json.dumps(metadata, sort_keys=True) + "\n").encode()
    (directory / "metadata.json").write_bytes(encoded)
    payloads = tuple(
        RenderArtifactPayload(
            kind=kind,
            relative_path=f"{JOB_A}/attempt-1/{name}",
            sha256=sha256(encoded if kind == "metadata" else kind.encode()).hexdigest(),
            byte_size=len(encoded) if kind == "metadata" else 1,
        )
        for kind, name in (
            ("video", "video.mp4"),
            ("thumbnail", "thumbnail.jpg"),
            ("render_log", "render.log"),
            ("metadata", "metadata.json"),
        )
    )

    report = record_completed_quality(
        engine=engine,
        artifact_root=root,
        job_id=JOB_A,
        completion=RenderJobCompletion(lease_token="a" * 64, artifacts=payloads),
    )

    assert report is not None
    assert report.actual_duration_seconds == 9.6
    assert report.target_duration_seconds == 90
    assert report.status.value == "failed"
    service = QualityReportService(QualityReportRepository(engine))
    assert service.latest_by_job(JOB_A, OWNER_A).id == report.id
    assert any(
        item.code.value == "source_not_approved" for item in service.diagnostics(report.id, OWNER_A)
    )
