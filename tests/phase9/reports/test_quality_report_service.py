from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from manim_workbench_api.quality.reports.errors import (
    QUALITY_REPORT_CONFLICT,
    QUALITY_REPORT_NOT_FOUND,
    QUALITY_REPORT_PROVENANCE_INVALID,
    QualityReportError,
)
from manim_workbench_api.quality.reports.repository import QualityReportRepository
from manim_workbench_api.quality.reports.service import QualityReportService
from manim_workbench_contracts import (
    PipelineStage,
    QualityDiagnostic,
    QualityDiagnosticCode,
    QualityHumanRatingRequest,
    QualityReport,
    QualitySeverity,
    QualityStatus,
)
from sqlalchemy import Engine, create_engine, text

from tests.workflows.migration_support import upgrade_workflow_database

OWNER_A = UUID("00000000-0000-0000-0000-000000000001")
OWNER_B = UUID("00000000-0000-0000-0000-000000000002")
PROJECT_A = UUID("00000000-0000-0000-0000-000000000011")
PROJECT_B = UUID("00000000-0000-0000-0000-000000000012")
PROMPT_A = UUID("00000000-0000-0000-0000-000000000021")
PLAN_A = UUID("00000000-0000-0000-0000-000000000031")
CODE_A = UUID("00000000-0000-0000-0000-000000000041")
JOB_A = UUID("00000000-0000-0000-0000-000000000051")
NOW = datetime(2026, 8, 5, 10, 0, tzinfo=timezone.utc)


def migrated_engine(tmp_path: Path) -> Engine:
    database_path = tmp_path / "quality-reports.db"
    upgrade_workflow_database(database_path)
    engine = create_engine(f"sqlite:///{database_path}")
    _seed_lineage(engine)
    return engine


def _seed_lineage(engine: Engine) -> None:
    plan = {
        "schema_version": "1.1",
        "title": "质量报告测试",
        "audience": "high_school",
        "language": "zh-CN",
        "target_duration_seconds": 90,
        "derivation_style": "step_by_step",
        "explicit_assumptions": [],
        "ambiguities": [],
        "scenes": [
            {
                "scene_number": 1,
                "teaching_goal": "解释函数图像",
                "formula_steps": [{"expression": "y=x^2", "explanation": "观察抛物线"}],
                "visual_intent": "显示坐标轴",
                "narration_placeholder": "说明顶点。",
            }
        ],
    }
    with engine.begin() as connection:
        for owner_id, email in (
            (OWNER_A, "owner-a@example.test"),
            (OWNER_B, "owner-b@example.test"),
        ):
            connection.execute(
                text("INSERT INTO users (id, email, created_at) VALUES (:id, :email, :created_at)"),
                {"id": str(owner_id), "email": email, "created_at": NOW.isoformat()},
            )
        for project_id, owner_id, title in (
            (PROJECT_A, OWNER_A, "Owner A"),
            (PROJECT_B, OWNER_B, "Owner B"),
        ):
            connection.execute(
                text(
                    "INSERT INTO projects (id, owner_id, title, created_at, updated_at) "
                    "VALUES (:id, :owner_id, :title, :created_at, :updated_at)"
                ),
                {
                    "id": str(project_id),
                    "owner_id": str(owner_id),
                    "title": title,
                    "created_at": NOW.isoformat(),
                    "updated_at": NOW.isoformat(),
                },
            )
        connection.execute(
            text(
                "INSERT INTO prompt_versions "
                "(id, project_id, owner_id, version, parent_version_id, created_at, prompt) "
                "VALUES (:id, :project_id, :owner_id, 1, NULL, :created_at, '解释二次函数')"
            ),
            {
                "id": str(PROMPT_A),
                "project_id": str(PROJECT_A),
                "owner_id": str(OWNER_A),
                "created_at": NOW.isoformat(),
            },
        )
        connection.execute(
            text(
                "INSERT INTO content_plan_versions "
                "(id, project_id, owner_id, version, parent_version_id, created_at, "
                "schema_version, content_json) VALUES "
                "(:id, :project_id, :owner_id, 1, NULL, :created_at, '1.1', :content_json)"
            ),
            {
                "id": str(PLAN_A),
                "project_id": str(PROJECT_A),
                "owner_id": str(OWNER_A),
                "created_at": NOW.isoformat(),
                "content_json": json.dumps(plan, ensure_ascii=False),
            },
        )
        connection.execute(
            text(
                "INSERT INTO code_versions "
                "(id, project_id, owner_id, version, parent_version_id, created_at, "
                "prompt_version_id, content_plan_version_id, source_code, source_sha256, "
                "scene_class, engine, engine_version, category, generation_mode, "
                "prompt_template_version, provider_model, assumptions_json) VALUES "
                "(:id, :project_id, :owner_id, 1, NULL, :created_at, :prompt_id, :plan_id, "
                "'from manim import Scene', :sha, 'GeneratedScene', 'manimce', '0.20.1', "
                "'function_visualization', 'full', 'phase7-v1', 'offline', '[]')"
            ),
            {
                "id": str(CODE_A),
                "project_id": str(PROJECT_A),
                "owner_id": str(OWNER_A),
                "created_at": NOW.isoformat(),
                "prompt_id": str(PROMPT_A),
                "plan_id": str(PLAN_A),
                "sha": "a" * 64,
            },
        )
    _insert_job(engine, JOB_A, CODE_A)


def _insert_job(engine: Engine, job_id: UUID, code_id: UUID) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO render_jobs "
                "(id, project_id, owner_id, code_version_id, profile, status, idempotency_key, "
                "created_at, attempt_count, state_version) VALUES "
                "(:id, :project_id, :owner_id, :code_id, 'preview', 'succeeded', :key, "
                ":created_at, 1, 1)"
            ),
            {
                "id": str(job_id),
                "project_id": str(PROJECT_A),
                "owner_id": str(OWNER_A),
                "code_id": str(code_id),
                "key": f"quality-report-job-{job_id.hex}",
                "created_at": NOW.isoformat(),
            },
        )


def diagnostic(*, message: str = "实际时长低于合格范围。") -> QualityDiagnostic:
    return QualityDiagnostic(
        code=QualityDiagnosticCode.DURATION_TOO_SHORT,
        severity=QualitySeverity.ERROR,
        stage=PipelineStage.QUALITY_ANALYSIS,
        message=message,
        suggestion="将解释动画合理分配到各教学场景。",
        evidence_ref="evidence/summary.json",
        measured_value=9.6,
        threshold_value=81,
    )


def report(
    service: QualityReportService,
    *,
    report_id: UUID | None = None,
    job_id: UUID = JOB_A,
    created_at: datetime = NOW,
    diagnostics: tuple[QualityDiagnostic, ...] | None = None,
) -> tuple[QualityReport, tuple[QualityDiagnostic, ...]]:
    values = diagnostics or (diagnostic(),)
    return (
        QualityReport(
            id=report_id or uuid4(),
            project_id=PROJECT_A,
            owner_id=OWNER_A,
            render_job_id=job_id,
            code_version_id=CODE_A,
            content_plan_version_id=PLAN_A,
            status=QualityStatus.REPAIR_REQUIRED,
            target_duration_seconds=90,
            estimated_duration_seconds=9.6,
            actual_duration_seconds=9.6,
            frame_rate=30,
            frame_count=288,
            score=20,
            repair_count=0,
            diagnostic_signature=service.diagnostic_signature(values),
            provider_model="offline",
            prompt_template_version="phase7-v1",
            content_plan_schema_version="1.1",
            manim_version="0.20.1",
            image_digest="sha256:" + "b" * 64,
            ast_policy_version="phase7-v1",
            diagnostic_policy_version="phase9-v1",
            created_at=created_at,
        ),
        values,
    )


def service(tmp_path: Path) -> QualityReportService:
    return QualityReportService(QualityReportRepository(migrated_engine(tmp_path)))


def test_append_get_latest_and_diagnostics_are_owner_scoped(tmp_path: Path) -> None:
    quality = service(tmp_path)
    item, diagnostics = report(quality)

    created = quality.append_report(item, diagnostics)

    assert created == item
    assert quality.get(item.id, OWNER_A) == item
    assert quality.latest_by_job(JOB_A, OWNER_A) == item
    assert quality.diagnostics(item.id, OWNER_A) == diagnostics


def test_diagnostic_signature_is_independent_of_input_order(tmp_path: Path) -> None:
    quality = service(tmp_path)
    first = diagnostic(message="第一个稳定诊断。")
    second = diagnostic(message="第二个稳定诊断。")

    assert quality.diagnostic_signature((first, second)) == quality.diagnostic_signature(
        (second, first)
    )


def test_missing_and_cross_owner_have_identical_not_found_errors(tmp_path: Path) -> None:
    quality = service(tmp_path)
    item, diagnostics = report(quality)
    quality.append_report(item, diagnostics)

    for action in (
        lambda: quality.get(item.id, OWNER_B),
        lambda: quality.get(uuid4(), OWNER_B),
        lambda: quality.latest_by_job(JOB_A, OWNER_B),
        lambda: quality.latest_by_job(uuid4(), OWNER_B),
        lambda: quality.list_by_project(PROJECT_A, OWNER_B, cursor=None, limit=10),
    ):
        with pytest.raises(QualityReportError) as caught:
            action()
        assert caught.value == QUALITY_REPORT_NOT_FOUND


def test_cursor_pagination_uses_creation_time_and_id_tiebreaker(tmp_path: Path) -> None:
    engine = migrated_engine(tmp_path)
    quality = QualityReportService(QualityReportRepository(engine))
    records = (
        (UUID("00000000-0000-0000-0000-000000000061"), 0),
        (UUID("00000000-0000-0000-0000-000000000062"), 0),
        (UUID("00000000-0000-0000-0000-000000000063"), 1),
    )
    for report_id, offset in records:
        job_id = uuid4()
        _insert_job(engine, job_id, CODE_A)
        item, diagnostics = report(
            quality,
            report_id=report_id,
            job_id=job_id,
            created_at=NOW + timedelta(seconds=offset),
            diagnostics=(diagnostic(message=f"时长问题 {offset}"),),
        )
        quality.append_report(item, diagnostics)

    first = quality.list_by_project(PROJECT_A, OWNER_A, cursor=None, limit=2)
    second = quality.list_by_project(PROJECT_A, OWNER_A, cursor=first.next_cursor, limit=2)

    assert [entry.created_at for entry in first.items] == [
        NOW + timedelta(seconds=1),
        NOW,
    ]
    assert [entry.id for entry in first.items] == [
        UUID("00000000-0000-0000-0000-000000000063"),
        UUID("00000000-0000-0000-0000-000000000062"),
    ]
    assert [entry.created_at for entry in second.items] == [NOW]
    assert [entry.id for entry in second.items] == [UUID("00000000-0000-0000-0000-000000000061")]
    assert first.next_cursor == first.items[-1].id
    assert second.next_cursor is None


def test_signature_conflict_and_provenance_failure_rollback(tmp_path: Path) -> None:
    quality = service(tmp_path)
    item, diagnostics = report(quality)
    quality.append_report(item, diagnostics)

    duplicate, duplicate_diagnostics = report(quality, report_id=uuid4())
    with pytest.raises(QualityReportError) as duplicate_error:
        quality.append_report(duplicate, duplicate_diagnostics)
    assert duplicate_error.value == QUALITY_REPORT_CONFLICT

    invalid = item.model_copy(update={"id": uuid4(), "render_job_id": uuid4()})
    with pytest.raises(QualityReportError) as provenance_error:
        quality.append_report(invalid, diagnostics)
    assert provenance_error.value == QUALITY_REPORT_PROVENANCE_INVALID

    wrong_owner = item.model_copy(update={"id": uuid4(), "owner_id": OWNER_B})
    with pytest.raises(QualityReportError) as owner_error:
        quality.append_report(wrong_owner, diagnostics)
    assert owner_error.value == QUALITY_REPORT_PROVENANCE_INVALID
    assert len(quality.list_by_project(PROJECT_A, OWNER_A, cursor=None, limit=10).items) == 1


def test_ratings_append_and_database_history_is_immutable(tmp_path: Path) -> None:
    engine = migrated_engine(tmp_path)
    quality = QualityReportService(QualityReportRepository(engine))
    item, diagnostics = report(quality)
    quality.append_report(item, diagnostics)

    rating = quality.append_human_rating(
        item.id, OWNER_A, QualityHumanRatingRequest(score=88, notes="教学节奏可接受。")
    )

    assert rating.score == 88
    assert quality.ratings(item.id, OWNER_A) == (rating,)
    with pytest.raises(QualityReportError) as secret_rating:
        quality.append_human_rating(
            item.id,
            OWNER_A,
            QualityHumanRatingRequest(score=50, notes="token=not-for-report-history"),
        )
    assert secret_rating.value == QUALITY_REPORT_PROVENANCE_INVALID
    assert quality.ratings(item.id, OWNER_A) == (rating,)
    with engine.begin() as connection:
        diagnostic_id = connection.execute(text("SELECT id FROM quality_diagnostics")).scalar_one()
        statements = (
            (
                text("UPDATE quality_reports SET created_at = created_at WHERE id = :id"),
                text("DELETE FROM quality_reports WHERE id = :id"),
                item.id,
            ),
            (
                text("UPDATE quality_diagnostics SET created_at = created_at WHERE id = :id"),
                text("DELETE FROM quality_diagnostics WHERE id = :id"),
                diagnostic_id,
            ),
            (
                text("UPDATE quality_ratings SET created_at = created_at WHERE id = :id"),
                text("DELETE FROM quality_ratings WHERE id = :id"),
                rating.id,
            ),
        )
        for update, delete, row_id in statements:
            with pytest.raises(Exception, match="append-only"):
                connection.execute(update, {"id": str(row_id)})
            with pytest.raises(Exception, match="append-only"):
                connection.execute(delete, {"id": str(row_id)})


def test_signature_is_recomputed_and_sensitive_diagnostics_are_not_persisted(
    tmp_path: Path,
) -> None:
    quality = service(tmp_path)
    item, diagnostics = report(quality)
    forged = item.model_copy(update={"diagnostic_signature": "0" * 64})
    with pytest.raises(QualityReportError) as forged_error:
        quality.append_report(forged, diagnostics)
    assert forged_error.value == QUALITY_REPORT_PROVENANCE_INVALID

    secret_item, secret_diagnostics = report(
        quality,
        diagnostics=(diagnostic(message="api_key=sk-should-never-be-persisted"),),
    )
    with pytest.raises(QualityReportError) as secret_error:
        quality.append_report(secret_item, secret_diagnostics)
    assert secret_error.value == QUALITY_REPORT_PROVENANCE_INVALID

    host_path_item, host_path_diagnostics = report(
        quality,
        diagnostics=(
                diagnostic().model_copy(update={"evidence_ref": "C:/Users/developer/secret.png"}),
        ),
    )
    with pytest.raises(QualityReportError) as path_error:
        quality.append_report(host_path_item, host_path_diagnostics)
    assert path_error.value == QUALITY_REPORT_PROVENANCE_INVALID

    source_item, source_diagnostics = report(
        quality,
        diagnostics=(
            diagnostic(message="from manim import Scene\nclass GeneratedScene(Scene): pass"),
        ),
    )
    with pytest.raises(QualityReportError) as source_error:
        quality.append_report(source_item, source_diagnostics)
    assert source_error.value == QUALITY_REPORT_PROVENANCE_INVALID
    assert quality.list_by_project(PROJECT_A, OWNER_A, cursor=None, limit=10).items == ()
