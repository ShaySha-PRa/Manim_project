from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from manim_workbench_api.quality.completion import record_completed_quality
from manim_workbench_api.quality.reports import QualityReportRepository, QualityReportService
from manim_workbench_contracts import RenderArtifactPayload, RenderJobCompletion
from sqlalchemy import text

from tests.phase9.reports.test_quality_report_service import (
    CODE_A,
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


def test_scientific_compiled_ir_uses_temporal_and_visual_quality_not_teaching_formula_gate(
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
            "sampled_frame_indices": [0, 675, 1349],
            "video": {"duration_seconds": 90, "fps": 15, "frame_count": 1350},
            "diagnostics": [],
        }
    }
    encoded = (json.dumps(metadata, sort_keys=True) + "\n").encode()
    (directory / "metadata.json").write_bytes(encoded)
    source = (
        "from manim import Scene, Text, Write\n"
        "class GeneratedScene(Scene):\n"
        "    def construct(self):\n"
        "        title = Text('scientific')\n"
        "        self.play(Write(title), run_time=90.0)\n"
    )
    code_id = uuid4()
    job_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO code_versions (id, project_id, owner_id, version, "
                "parent_version_id, created_at, prompt_version_id, content_plan_version_id, "
                "source_code, source_sha256, scene_class, engine, engine_version, category, "
                "generation_mode, prompt_template_version, provider_model, assumptions_json) "
                "SELECT :id, project_id, owner_id, version + 1, id, created_at, "
                "prompt_version_id, content_plan_version_id, :source, :sha, scene_class, engine, "
                "engine_version, category, 'compiled_ir', 'animation-agent-v2', "
                "'compiler+tools', assumptions_json FROM code_versions WHERE id = :parent_id"
            ),
            {
                "source": source,
                "sha": sha256(source.encode()).hexdigest(),
                "id": str(code_id),
                "parent_id": str(CODE_A),
            },
        )
        connection.execute(
            text(
                "INSERT INTO render_jobs (id, project_id, owner_id, code_version_id, profile, "
                "status, idempotency_key, created_at, attempt_count, state_version) "
                "SELECT :job_id, project_id, owner_id, :code_id, 'preview', 'succeeded', "
                ":key, created_at, 1, 1 FROM render_jobs WHERE id = :parent_job_id"
            ),
            {
                "job_id": str(job_id),
                "code_id": str(code_id),
                "key": f"scientific-quality-{job_id.hex}",
                "parent_job_id": str(JOB_A),
            },
        )
    scientific_directory = root / str(job_id) / "attempt-1"
    scientific_directory.mkdir(parents=True)
    (scientific_directory / "metadata.json").write_bytes(encoded)
    payloads = _payloads(encoded, job_id=job_id)

    report = record_completed_quality(
        engine=engine,
        artifact_root=root,
        job_id=job_id,
        completion=RenderJobCompletion(lease_token="a" * 64, artifacts=payloads),
    )

    assert report is not None
    assert report.status.value == "passed"
    diagnostics = QualityReportService(QualityReportRepository(engine)).diagnostics(
        report.id, OWNER_A
    )
    assert "key_formula_missing" not in {item.code.value for item in diagnostics}


def test_failed_quality_marks_job_failed_without_registering_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    from manim_workbench_api.jobs.router import complete_render_job

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
    lease_token = "a" * 64
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE render_jobs SET status = 'running', lease_owner = 'runner-test', "
                "lease_token = :lease_token, lease_expires_at = :expires, "
                "heartbeat_at = :heartbeat WHERE id = :id"
            ),
            {
                "lease_token": lease_token,
                "expires": (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
                "heartbeat": datetime.now(timezone.utc).isoformat(),
                "id": str(JOB_A),
            },
        )
    monkeypatch.setattr("manim_workbench_api.jobs.router.get_artifact_root", lambda: root)

    response = complete_render_job(
        JOB_A,
        RenderJobCompletion(lease_token=lease_token, artifacts=_payloads(encoded)),
        request_token="internal-test-token",
        expected_token="internal-test-token",
        engine=engine,
        publisher=None,  # type: ignore[arg-type]
    )

    assert response.status.value == "failed"  # type: ignore[union-attr]
    assert response.failure_code == "render_failed"  # type: ignore[union-attr]
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM artifacts WHERE render_job_id = :id"),
                {"id": str(JOB_A)},
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM quality_reports WHERE render_job_id = :id"),
                {"id": str(JOB_A)},
            ).scalar_one()
            == 1
        )


def _payloads(
    metadata: bytes,
    *,
    job_id=JOB_A,  # type: ignore[no-untyped-def]
) -> tuple[RenderArtifactPayload, ...]:
    return tuple(
        RenderArtifactPayload(
            kind=kind,
            relative_path=f"{job_id}/attempt-1/{name}",
            sha256=sha256(metadata if kind == "metadata" else kind.encode()).hexdigest(),
            byte_size=len(metadata) if kind == "metadata" else 1,
        )
        for kind, name in (
            ("video", "video.mp4"),
            ("thumbnail", "thumbnail.jpg"),
            ("render_log", "render.log"),
            ("metadata", "metadata.json"),
        )
    )
