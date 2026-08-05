from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from manim_workbench_api.quality.reports import QualityReportRepository, QualityReportService
from manim_workbench_api.quality.temporal import MediaTiming
from manim_workbench_contracts import (
    ContentPlanDraft,
    ContentPlanVersion,
    PipelineStage,
    QualityDiagnostic,
    QualityDiagnosticCode,
    QualityReport,
    QualitySeverity,
    QualityStatus,
    RenderJobCompletion,
)
from manim_workbench_runner.rendering.models import MANIM_IMAGE_DIGEST, MANIM_VERSION
from sqlalchemy import Engine, text

from .orchestration import diagnose_content_plan_timeline

_MAX_METADATA_BYTES = 256 * 1024

_VISUAL_SUGGESTIONS = {
    "blank_frame": "Keep visible instructional content in every active teaching scene.",
    "long_static_segment": "Replace static holds with progressive explanatory animation.",
    "object_out_of_bounds": "Move the affected object inside the visible frame.",
    "object_overlap": "Increase spacing between overlapping teaching objects.",
    "text_too_small": "Increase instructional text size.",
    "cjk_glyph_missing": "Use the approved CJK font for Chinese text.",
    "object_missing": "Restore the missing planned teaching object.",
    "media_metadata_invalid": "Retry the render and media analysis stage.",
}


def record_completed_quality(
    *,
    engine: Engine,
    artifact_root: Path,
    job_id: UUID,
    completion: RenderJobCompletion,
) -> QualityReport | None:
    """Persist one immutable report after a successful completion, when evidence is available."""
    if not _quality_schema_exists(engine):
        return None
    metadata_artifact = next(
        (artifact for artifact in completion.artifacts if artifact.kind.value == "metadata"), None
    )
    if metadata_artifact is None:
        return None
    metadata_path = _artifact_path(artifact_root, metadata_artifact.relative_path)
    if metadata_path is None:
        return None
    if sha256(metadata_path.read_bytes()).hexdigest() != metadata_artifact.sha256:
        return None
    metadata = _metadata(metadata_path)
    row = _lineage(engine, job_id)
    if row is None:
        return None
    draft = ContentPlanDraft.model_validate_json(str(row["content_json"]))
    plan = ContentPlanVersion(
        id=UUID(str(row["content_plan_version_id"])),
        project_id=UUID(str(row["project_id"])),
        owner_id=UUID(str(row["owner_id"])),
        version=int(row["plan_version"]),
        parent_version_id=UUID(str(row["plan_parent_version_id"]))
        if row["plan_parent_version_id"]
        else None,
        created_at=_timestamp(row["plan_created_at"]),
        **draft.model_dump(),
    )
    video = _video_timing(metadata)
    temporal, temporal_diagnostics = diagnose_content_plan_timeline(
        source_code=str(row["source_code"]),
        content_plan=plan,
        actual_media=video,
    )
    diagnostics = temporal_diagnostics + _visual_diagnostics(metadata)
    service = QualityReportService(QualityReportRepository(engine))
    signature = service.diagnostic_signature(diagnostics)
    has_errors = any(item.severity is QualitySeverity.ERROR for item in diagnostics)
    has_warnings = any(item.severity is QualitySeverity.WARNING for item in diagnostics)
    status = (
        QualityStatus.FAILED
        if has_errors
        else QualityStatus.DEGRADED
        if has_warnings
        else QualityStatus.PASSED
    )
    report = QualityReport(
        id=uuid4(),
        project_id=UUID(str(row["project_id"])),
        owner_id=UUID(str(row["owner_id"])),
        render_job_id=job_id,
        code_version_id=UUID(str(row["code_version_id"])),
        content_plan_version_id=plan.id,
        status=status,
        target_duration_seconds=plan.target_duration_seconds,
        estimated_duration_seconds=temporal.estimated_duration_seconds,
        actual_duration_seconds=video.duration_seconds,
        frame_rate=video.frame_rate,
        frame_count=video.frame_count,
        score=max(
            0,
            100
            - 25 * sum(item.severity is QualitySeverity.ERROR for item in diagnostics)
            - 8 * sum(item.severity is QualitySeverity.WARNING for item in diagnostics),
        ),
        repair_count=0,
        diagnostic_signature=signature,
        provider_model=str(row["provider_model"] or "deterministic-template"),
        prompt_template_version=str(row["prompt_template_version"] or "phase7-legacy"),
        content_plan_schema_version=str(row["plan_schema_version"]),
        manim_version=MANIM_VERSION,
        image_digest=MANIM_IMAGE_DIGEST,
        ast_policy_version="phase7-ast-v1",
        diagnostic_policy_version="phase9-deterministic-v1",
        created_at=datetime.now(timezone.utc),
    )
    return service.append_report(report, diagnostics)


def _quality_schema_exists(engine: Engine) -> bool:
    with engine.connect() as connection:
        return (
            connection.execute(
                text(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'quality_reports'"
                )
            ).scalar_one_or_none()
            is not None
        )


def _artifact_path(root: Path, relative: str) -> Path | None:
    try:
        resolved_root = root.resolve(strict=True)
        candidate = (resolved_root / relative).resolve(strict=True)
    except OSError:
        return None
    if not candidate.is_relative_to(resolved_root) or candidate.is_symlink():
        return None
    if not candidate.is_file() or candidate.stat().st_size > _MAX_METADATA_BYTES:
        return None
    return candidate


def _metadata(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _lineage(engine: Engine, job_id: UUID):  # type: ignore[no-untyped-def]
    with engine.connect() as connection:
        return (
            connection.execute(
                text(
                    """
                SELECT jobs.project_id, jobs.owner_id, jobs.code_version_id,
                       code.content_plan_version_id, code.source_code,
                       code.prompt_template_version, code.provider_model,
                       plan.version AS plan_version,
                       plan.parent_version_id AS plan_parent_version_id,
                       plan.created_at AS plan_created_at,
                       plan.schema_version AS plan_schema_version, plan.content_json
                FROM render_jobs AS jobs
                JOIN code_versions AS code ON code.id = jobs.code_version_id
                JOIN content_plan_versions AS plan ON plan.id = code.content_plan_version_id
                WHERE jobs.id = :job_id AND jobs.status = 'succeeded'
                """
                ),
                {"job_id": str(job_id)},
            )
            .mappings()
            .one_or_none()
        )


def _timestamp(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _video_timing(metadata: dict[str, object]) -> MediaTiming:
    quality = metadata.get("quality")
    video = quality.get("video") if isinstance(quality, dict) else None
    if not isinstance(video, dict):
        return MediaTiming(None, None, None)
    try:
        return MediaTiming(
            float(video["duration_seconds"]),
            float(video["fps"]),
            int(video["frame_count"]),
        )
    except (KeyError, TypeError, ValueError):
        return MediaTiming(None, None, None)


def _visual_diagnostics(metadata: dict[str, object]) -> tuple[QualityDiagnostic, ...]:
    quality = metadata.get("quality")
    raw_items = quality.get("diagnostics") if isinstance(quality, dict) else None
    if not isinstance(raw_items, list):
        raw_items = [{"code": "media_metadata_invalid", "severity": "error"}]
    diagnostics: list[QualityDiagnostic] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        try:
            code = QualityDiagnosticCode(str(raw["code"]))
            severity = QualitySeverity(str(raw["severity"]))
        except (KeyError, ValueError):
            continue
        diagnostics.append(
            QualityDiagnostic(
                code=code,
                severity=severity,
                stage=PipelineStage.QUALITY_ANALYSIS,
                message=str(raw.get("summary") or "Rendered media did not pass quality analysis."),
                suggestion=_VISUAL_SUGGESTIONS.get(code.value, "Regenerate the affected scene."),
                measured_value=_number(raw.get("measured_value")),
                threshold_value=_number(raw.get("threshold_value")),
            )
        )
    return tuple(diagnostics)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)
