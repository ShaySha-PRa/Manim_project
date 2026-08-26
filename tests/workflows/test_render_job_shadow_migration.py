from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import UUID

import manim_workbench_api.database_migrations.render_job_typed_sources as migration
import pytest
from alembic import command
from alembic.config import Config
from manim_workbench_api.database import create_database_engine
from manim_workbench_api.jobs.repository import JobRepository
from sqlalchemy import inspect, text

from scripts import validate_render_job_shadow_migration as shadow

ROOT = Path(__file__).resolve().parents[2]

OWNER_ID = "00000000-0000-0000-0000-000000000001"
PROJECT_ID = "10000000-0000-0000-0000-000000000001"
PROMPT_ID = "20000000-0000-0000-0000-000000000001"
PLAN_ID = "30000000-0000-0000-0000-000000000001"
CODE_ID = "40000000-0000-0000-0000-000000000001"
SUCCEEDED_JOB_ID = "50000000-0000-0000-0000-000000000001"
QUEUED_JOB_ID = "50000000-0000-0000-0000-000000000002"
ARTIFACT_ID = "60000000-0000-0000-0000-000000000001"
QUALITY_ID = "70000000-0000-0000-0000-000000000001"
NOW = "2026-08-24T00:00:00+00:00"
SOURCE = "from manim import Scene\nclass GeneratedScene(Scene):\n    pass\n"


def _0008_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "release-0008.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0008_asset_versions")
    engine = create_database_engine(f"sqlite:///{database_path}")
    source_hash = sha256(SOURCE.encode()).hexdigest()
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id,email,created_at) VALUES (:id,'owner@test.dev',:now)"),
            {"id": OWNER_ID, "now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO projects (id,owner_id,title,created_at,updated_at) "
                "VALUES (:id,:owner,'Existing project',:now,:now)"
            ),
            {"id": PROJECT_ID, "owner": OWNER_ID, "now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO prompt_versions "
                "(id,project_id,owner_id,version,parent_version_id,created_at,prompt) "
                "VALUES (:id,:project,:owner,1,NULL,:now,'Existing prompt')"
            ),
            {"id": PROMPT_ID, "project": PROJECT_ID, "owner": OWNER_ID, "now": NOW},
        )
        connection.execute(
            text(
                "INSERT INTO content_plan_versions "
                "(id,project_id,owner_id,version,parent_version_id,created_at,schema_version,"
                "content_json) VALUES (:id,:project,:owner,1,NULL,:now,'1.1',:content)"
            ),
            {
                "id": PLAN_ID,
                "project": PROJECT_ID,
                "owner": OWNER_ID,
                "now": NOW,
                "content": '{"target_duration_seconds":30}',
            },
        )
        connection.execute(
            text(
                "INSERT INTO code_versions "
                "(id,project_id,owner_id,version,parent_version_id,created_at,prompt_version_id,"
                "content_plan_version_id,source_code,source_sha256,engine,engine_version,"
                "scene_class,category,generation_mode,assumptions_json) VALUES "
                "(:id,:project,:owner,1,NULL,:now,:prompt,:plan,:source,:sha,'manimce',"
                "'0.21.0','GeneratedScene','formula_derivation','full','[]')"
            ),
            {
                "id": CODE_ID,
                "project": PROJECT_ID,
                "owner": OWNER_ID,
                "now": NOW,
                "prompt": PROMPT_ID,
                "plan": PLAN_ID,
                "source": SOURCE,
                "sha": source_hash,
            },
        )
        for job_id, status, key in (
            (SUCCEEDED_JOB_ID, "succeeded", "existing-release-job"),
            (QUEUED_JOB_ID, "queued", "existing-queued-job"),
        ):
            connection.execute(
                text(
                    "INSERT INTO render_jobs "
                    "(id,project_id,owner_id,code_version_id,profile,status,idempotency_key,"
                    "created_at) VALUES (:id,:project,:owner,:code,'preview',:status,:key,:now)"
                ),
                {
                    "id": job_id,
                    "project": PROJECT_ID,
                    "owner": OWNER_ID,
                    "code": CODE_ID,
                    "status": status,
                    "key": key,
                    "now": NOW,
                },
            )
        connection.execute(
            text(
                "INSERT INTO artifacts "
                "(id,project_id,owner_id,render_job_id,kind,relative_path,sha256,byte_size,"
                "created_at) VALUES (:id,:project,:owner,:job,'video','existing.mp4',:sha,123,:now)"
            ),
            {
                "id": ARTIFACT_ID,
                "project": PROJECT_ID,
                "owner": OWNER_ID,
                "job": SUCCEEDED_JOB_ID,
                "sha": "b" * 64,
                "now": NOW,
            },
        )
        connection.execute(
            text(
                "INSERT INTO quality_reports "
                "(id,project_id,owner_id,render_job_id,code_version_id,content_plan_version_id,"
                "status,target_duration_seconds,repair_count,diagnostic_signature,provider_model,"
                "prompt_template_version,content_plan_schema_version,manim_version,image_digest,"
                "ast_policy_version,diagnostic_policy_version,created_at) VALUES "
                "(:id,:project,:owner,:job,:code,:plan,'passed',30,0,:signature,'test-model',"
                "'test-template','1.1','0.21.0',:image,'ast-v1','diagnostic-v1',:now)"
            ),
            {
                "id": QUALITY_ID,
                "project": PROJECT_ID,
                "owner": OWNER_ID,
                "job": SUCCEEDED_JOB_ID,
                "code": CODE_ID,
                "plan": PLAN_ID,
                "signature": "c" * 64,
                "image": f"sha256:{'d' * 64}",
                "now": NOW,
            },
        )
    engine.dispose()
    return database_path


def _snapshot(database_path: Path) -> dict[str, list[tuple[object, ...]]]:
    engine = create_database_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        result = {
            table: list(connection.execute(text(f"SELECT * FROM {table} ORDER BY 1")))
            for table in ("render_jobs", "artifacts", "job_events", "quality_reports")
        }
    engine.dispose()
    return result


def test_shadow_upgrade_preserves_release_evidence_and_existing_claim(tmp_path: Path) -> None:
    database_path = _0008_database(tmp_path)
    before = _snapshot(database_path)
    backup_path = tmp_path / "release-0008.backup.db"

    evidence = shadow.rebuild_render_jobs(
        database_path, backup_path, typed_source=True
    )

    assert evidence.render_job_count == 2
    assert evidence.foreign_key_check == evidence.integrity_check == "ok"
    assert backup_path.is_file()
    after = _snapshot(database_path)
    for table in ("artifacts", "job_events", "quality_reports"):
        assert after[table] == before[table]
    assert [row[:4] + row[5:] for row in after["render_jobs"]] == before["render_jobs"]
    assert all(row[4] is None for row in after["render_jobs"])

    engine = create_database_engine(f"sqlite:///{database_path}")
    columns = {item["name"]: item for item in inspect(engine).get_columns("render_jobs")}
    assert columns["code_version_id"]["nullable"] is True
    assert columns["program_render_segment_id"]["nullable"] is True
    claim = JobRepository(engine).claim(UUID(QUEUED_JOB_ID), "shadow-test-runner", 30)
    assert claim.record is not None
    assert claim.work_item is not None
    assert claim.work_item.source_code == SOURCE
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        assert connection.execute(text("PRAGMA integrity_check")).one() == ("ok",)
        trigger_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' "
                "AND name LIKE 'render_jobs_phase8_event_after_%'"
            )
        ).scalar_one()
        assert trigger_count == 2
        assert connection.execute(
            text("SELECT COUNT(*) FROM job_events WHERE render_job_id=:job"),
            {"job": QUEUED_JOB_ID},
        ).scalar_one() == 2
    engine.dispose()


def test_shadow_rebuild_rolls_back_if_post_replace_integrity_check_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = _0008_database(tmp_path)
    before = _snapshot(database_path)
    original_validate = migration._validate_integrity
    calls = 0

    def fail_after_replace(database):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected post-replace integrity failure")
        return original_validate(database)

    monkeypatch.setattr(migration, "_validate_integrity", fail_after_replace)
    with pytest.raises(RuntimeError, match="injected post-replace"):
        shadow.rebuild_render_jobs(
            database_path, tmp_path / "rollback.backup.db", typed_source=True
        )

    assert _snapshot(database_path) == before
    engine = create_database_engine(f"sqlite:///{database_path}")
    assert "program_render_segment_id" not in {
        item["name"] for item in inspect(engine).get_columns("render_jobs")
    }
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).one() == (1,)
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()


def test_shadow_round_trip_and_scientific_job_downgrade_refusal(tmp_path: Path) -> None:
    database_path = _0008_database(tmp_path)
    shadow.rebuild_render_jobs(
        database_path, tmp_path / "upgrade.backup.db", typed_source=True
    )
    shadow.rebuild_render_jobs(
        database_path, tmp_path / "downgrade.backup.db", typed_source=False
    )
    engine = create_database_engine(f"sqlite:///{database_path}")
    assert "program_render_segment_id" not in {
        item["name"] for item in inspect(engine).get_columns("render_jobs")
    }
    engine.dispose()

    shadow.rebuild_render_jobs(
        database_path, tmp_path / "upgrade-again.backup.db", typed_source=True
    )
    engine = create_database_engine(f"sqlite:///{database_path}")
    scientific_job_id = "50000000-0000-0000-0000-000000000003"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO render_jobs "
                "(id,project_id,owner_id,code_version_id,program_render_segment_id,profile,"
                "status,idempotency_key,created_at) VALUES "
                "(:id,:project,:owner,NULL,:segment,'preview','queued','scientific-job',:now)"
            ),
            {
                "id": scientific_job_id,
                "project": PROJECT_ID,
                "owner": OWNER_ID,
                "segment": "80000000-0000-0000-0000-000000000001",
                "now": NOW,
            },
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="cannot downgrade"):
        shadow.rebuild_render_jobs(
            database_path, tmp_path / "blocked.backup.db", typed_source=False
        )
    engine = create_database_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT program_render_segment_id FROM render_jobs WHERE id=:id"),
            {"id": scientific_job_id},
        ).scalar_one() == "80000000-0000-0000-0000-000000000001"
        assert connection.execute(text("PRAGMA foreign_keys")).one() == (1,)
    engine.dispose()


def test_shadow_tool_refuses_paths_outside_tmp(tmp_path: Path) -> None:
    database_path = _0008_database(tmp_path)
    with pytest.raises(ValueError, match="restricted to /tmp"):
        shadow.rebuild_render_jobs(
            database_path,
            ROOT / "forbidden-backup.db",
            typed_source=True,
        )
