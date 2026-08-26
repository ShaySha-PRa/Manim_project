from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from manim_workbench_api.database import create_database_engine
from manim_workbench_api.database_migrations.protected_render_job_migration import (
    run_protected_migration,
)
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError

ROOT = Path(__file__).resolve().parents[2]


def _upgrade(tmp_path: Path):  # type: ignore[no-untyped-def]
    database_path = tmp_path / "workflow.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0008_asset_versions")
    run_protected_migration(
        database_path=database_path,
        backup_path=tmp_path / "workflow.pre-0009.db",
        alembic_config_path=ROOT / "alembic.ini",
        mode="upgrade",
        services_stopped=True,
    )
    command.upgrade(config, "head")
    return create_database_engine(f"sqlite:///{database_path}")


def test_0010_creates_version_run_event_and_composition_schema(tmp_path: Path) -> None:
    engine = _upgrade(tmp_path)
    tables = set(inspect(engine).get_table_names())
    assert {
        "video_workflows",
        "video_workflow_versions",
        "scene_blocks",
        "scene_block_versions",
        "scene_block_runs",
        "scene_block_run_events",
        "workflow_composition_runs",
        "workflow_composition_run_events",
        "program_render_runs",
        "program_render_segments",
        "workflow_artifacts",
        "workflow_tasks",
    } <= tables
    artifact_columns = {
        column["name"] for column in inspect(engine).get_columns("workflow_artifacts")
    }
    assert "duration_seconds" in artifact_columns
    scene_event_foreign_keys = inspect(engine).get_foreign_keys("scene_block_run_events")
    assert {
        tuple(item["constrained_columns"]): item["referred_table"]
        for item in scene_event_foreign_keys
    }[("preview_artifact_id",)] == "workflow_artifacts"
    assert {
        tuple(item["constrained_columns"]): item["referred_table"]
        for item in scene_event_foreign_keys
    }[("final_artifact_id",)] == "workflow_artifacts"
    composition_event_foreign_keys = inspect(engine).get_foreign_keys(
        "workflow_composition_run_events"
    )
    assert {
        tuple(item["constrained_columns"]): item["referred_table"]
        for item in composition_event_foreign_keys
    }[("artifact_id",)] == "workflow_artifacts"
    with engine.connect() as connection:
        triggers = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            )
        }
    for table in (
        "scene_block_versions",
        "video_workflow_versions",
        "scene_block_runs",
        "scene_block_run_events",
        "workflow_composition_runs",
        "workflow_composition_run_events",
    ):
        assert f"{table}_prevent_update" in triggers
        assert f"{table}_prevent_delete" in triggers
    assert "scene_block_run_events_enforce_state_version" in triggers
    assert "workflow_composition_run_events_enforce_state_version" in triggers


def test_0010_blocks_version_mutation_and_non_monotonic_run_events(tmp_path: Path) -> None:
    engine = _upgrade(tmp_path)
    now = "2026-08-23T00:00:00+00:00"
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id,email,created_at) VALUES ('owner','o@test.dev',:now)"),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO projects (id,owner_id,title,created_at) "
                "VALUES ('project','owner','Workflow',:now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO video_workflows (id,project_id,owner_id,created_at) "
                "VALUES ('workflow','project','owner',:now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO scene_blocks (id,workflow_id,project_id,owner_id,created_at) "
                "VALUES ('block','workflow','project','owner',:now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO scene_block_versions "
                "(id,scene_block_id,workflow_id,project_id,owner_id,version,"
                "parent_version_id,title,prompt,pipeline_mode,target_duration_seconds,"
                "asset_version_ids_json,created_at) VALUES "
                "('block-v1','block','workflow','project','owner',1,NULL,'Scene','Prompt',"
                "'auto',30,'[]',:now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO video_workflow_versions "
                "(id,workflow_id,project_id,owner_id,version,parent_version_id,"
                "global_brief_json,nodes_json,edges_json,created_at) VALUES "
                "('workflow-v1','workflow','project','owner',1,NULL,'{}','[]','[]',:now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO scene_block_runs "
                "(id,scene_block_version_id,workflow_version_id,project_id,owner_id,"
                "cache_key,idempotency_key,created_at) VALUES "
                "('run','block-v1','workflow-v1','project','owner',:cache,:key,:now)"
            ),
            {"cache": "a" * 64, "key": "scene-run-idempotency", "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO scene_block_run_events "
                "(id,run_id,owner_id,state_version,status,created_at) "
                "VALUES ('event-0','run','owner',0,'queued',:now)"
            ),
            {"now": now},
        )

    with pytest.raises(IntegrityError, match="append-only"):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE scene_block_versions SET title = 'Changed' WHERE id = 'block-v1'")
            )
    with pytest.raises(IntegrityError, match="monotonic"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO scene_block_run_events "
                    "(id,run_id,owner_id,state_version,status,created_at) "
                    "VALUES ('event-2','run','owner',2,'rendering',:now)"
                ),
                {"now": now},
            )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scene_block_run_events "
                "(id,run_id,owner_id,state_version,status,created_at) "
                "VALUES ('event-1','run','owner',1,'planning',:now)"
            ),
            {"now": now},
        )
    with pytest.raises(IntegrityError, match="append-only"):
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM scene_block_run_events WHERE id = 'event-1'"))


def test_0010_round_trip_preserves_existing_release_data(tmp_path: Path) -> None:
    database_path = tmp_path / "round-trip.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0008_asset_versions")
    engine = create_database_engine(f"sqlite:///{database_path}")
    now = "2026-08-23T00:00:00+00:00"
    ids = {
        "owner": "00000000-0000-0000-0000-000000000001",
        "project": "10000000-0000-0000-0000-000000000001",
        "prompt": "20000000-0000-0000-0000-000000000001",
        "plan": "30000000-0000-0000-0000-000000000001",
        "code": "40000000-0000-0000-0000-000000000001",
        "job": "50000000-0000-0000-0000-000000000001",
        "artifact": "60000000-0000-0000-0000-000000000001",
    }
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id,email,created_at) VALUES (:id,'owner@test.dev',:now)"),
            {"id": ids["owner"], "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO projects (id,owner_id,title,created_at,updated_at) "
                "VALUES (:id,:owner,'Existing project',:now,:now)"
            ),
            {"id": ids["project"], "owner": ids["owner"], "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO prompt_versions "
                "(id,project_id,owner_id,version,parent_version_id,created_at,prompt) "
                "VALUES (:id,:project,:owner,1,NULL,:now,'Existing prompt')"
            ),
            {"id": ids["prompt"], "project": ids["project"], "owner": ids["owner"], "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO content_plan_versions "
                "(id,project_id,owner_id,version,parent_version_id,created_at,schema_version,"
                "content_json) VALUES (:id,:project,:owner,1,NULL,:now,'1.1','{}')"
            ),
            {"id": ids["plan"], "project": ids["project"], "owner": ids["owner"], "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO code_versions "
                "(id,project_id,owner_id,version,parent_version_id,created_at,prompt_version_id,"
                "content_plan_version_id,source_code,source_sha256,engine,engine_version,"
                "scene_class,category,generation_mode,assumptions_json) VALUES "
                "(:id,:project,:owner,1,NULL,:now,:prompt,:plan,'class Scene: pass',:sha,"
                "'manimce','0.20.1','Scene','formula_derivation','full','[]')"
            ),
            {
                "id": ids["code"],
                "project": ids["project"],
                "owner": ids["owner"],
                "now": now,
                "prompt": ids["prompt"],
                "plan": ids["plan"],
                "sha": "a" * 64,
            },
        )
        connection.execute(
            text(
                "INSERT INTO render_jobs "
                "(id,project_id,owner_id,code_version_id,profile,status,idempotency_key,"
                "created_at) VALUES (:id,:project,:owner,:code,'preview','succeeded','existing',"
                ":now)"
            ),
            {
                "id": ids["job"],
                "project": ids["project"],
                "owner": ids["owner"],
                "code": ids["code"],
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO artifacts "
                "(id,project_id,owner_id,render_job_id,kind,relative_path,sha256,byte_size,"
                "created_at) VALUES (:id,:project,:owner,:job,'video','existing.mp4',:sha,123,:now)"
            ),
            {
                "id": ids["artifact"],
                "project": ids["project"],
                "owner": ids["owner"],
                "job": ids["job"],
                "sha": "b" * 64,
                "now": now,
            },
        )

    engine.dispose()
    run_protected_migration(
        database_path=database_path,
        backup_path=tmp_path / "round-trip.pre-0009-upgrade.db",
        alembic_config_path=ROOT / "alembic.ini",
        mode="upgrade",
        services_stopped=True,
    )
    command.upgrade(config, "0010_video_workflows")
    command.downgrade(config, "0009_render_job_typed_sources")
    run_protected_migration(
        database_path=database_path,
        backup_path=tmp_path / "round-trip.pre-0009-downgrade.db",
        alembic_config_path=ROOT / "alembic.ini",
        mode="downgrade",
        services_stopped=True,
    )
    run_protected_migration(
        database_path=database_path,
        backup_path=tmp_path / "round-trip.pre-0009-upgrade-again.db",
        alembic_config_path=ROOT / "alembic.ini",
        mode="upgrade",
        services_stopped=True,
    )
    command.upgrade(config, "0010_video_workflows")

    engine = create_database_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0010_video_workflows"
        )
        assert connection.execute(
            text("SELECT title FROM projects WHERE id=:id"), {"id": ids["project"]}
        ).scalar_one() == "Existing project"
        assert connection.execute(
            text("SELECT source_sha256 FROM code_versions WHERE id=:id"), {"id": ids["code"]}
        ).scalar_one() == "a" * 64
        assert connection.execute(
            text("SELECT status FROM render_jobs WHERE id=:id"), {"id": ids["job"]}
        ).scalar_one() == "succeeded"
        artifact = connection.execute(
            text("SELECT sha256,byte_size FROM artifacts WHERE id=:id"),
            {"id": ids["artifact"]},
        ).one()
        assert artifact == ("b" * 64, 123)


def test_0010_failure_leaves_0009_retryable(tmp_path: Path) -> None:
    database_path = tmp_path / "retry-0010.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0008_asset_versions")
    run_protected_migration(
        database_path=database_path,
        backup_path=tmp_path / "retry-0010.pre-0009.db",
        alembic_config_path=ROOT / "alembic.ini",
        mode="upgrade",
        services_stopped=True,
    )
    engine = create_database_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE video_workflows (blocker INTEGER)"))

    with pytest.raises(OperationalError, match="video_workflows"):
        command.upgrade(config, "0010_video_workflows")

    with engine.begin() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0009_render_job_typed_sources"
        )
        connection.execute(text("DROP TABLE video_workflows"))
    command.upgrade(config, "0010_video_workflows")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0010_video_workflows"
        )


def test_0010_downgrade_refuses_scientific_job_before_dropping_tables(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "scientific-downgrade.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0008_asset_versions")
    run_protected_migration(
        database_path=database_path,
        backup_path=tmp_path / "scientific-downgrade.pre-0009.db",
        alembic_config_path=ROOT / "alembic.ini",
        mode="upgrade",
        services_stopped=True,
    )
    command.upgrade(config, "0010_video_workflows")
    engine = create_database_engine(f"sqlite:///{database_path}")
    now = "2026-08-24T00:00:00+00:00"
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id,email,created_at) VALUES ('owner','o@test.dev',:now)"),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO projects (id,owner_id,title,created_at) "
                "VALUES ('project','owner','Workflow',:now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO video_workflows (id,project_id,owner_id,created_at) "
                "VALUES ('workflow','project','owner',:now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO scene_blocks (id,workflow_id,project_id,owner_id,created_at) "
                "VALUES ('block','workflow','project','owner',:now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO scene_block_versions "
                "(id,scene_block_id,workflow_id,project_id,owner_id,version,title,prompt,"
                "pipeline_mode,target_duration_seconds,asset_version_ids_json,created_at) "
                "VALUES ('block-v1','block','workflow','project','owner',1,'Scene','Prompt',"
                "'scientific',30,'[]',:now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO video_workflow_versions "
                "(id,workflow_id,project_id,owner_id,version,global_brief_json,nodes_json,"
                "edges_json,created_at) VALUES "
                "('workflow-v1','workflow','project','owner',1,'{}','[]','[]',:now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO scene_block_runs "
                "(id,scene_block_version_id,workflow_version_id,project_id,owner_id,cache_key,"
                "idempotency_key,created_at) VALUES "
                "('scene-run','block-v1','workflow-v1','project','owner',:cache,:key,:now)"
            ),
            {"cache": "a" * 64, "key": "scientific-scene-run", "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO program_render_runs "
                "(id,scene_block_run_id,project_id,owner_id,profile,program_sha256,"
                "quality_policy,status,segment_count,created_at) VALUES "
                "('program-run','scene-run','project','owner','preview',:hash,'scientific',"
                "'rendering',1,:now)"
            ),
            {"hash": "b" * 64, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO program_render_segments "
                "(id,program_render_run_id,segment_index,source_code,source_sha256,scene_class,"
                "target_duration_seconds,render_job_id,status) VALUES "
                "('segment','program-run',0,'class ScientificScene: pass',:hash,"
                "'ScientificScene',30,'job','queued')"
            ),
            {"hash": "c" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO render_jobs "
                "(id,project_id,owner_id,code_version_id,program_render_segment_id,profile,"
                "status,idempotency_key,created_at,concat_group_id,segment_index) VALUES "
                "('job','project','owner',NULL,'segment','preview','queued',"
                "'scientific-render-job',:now,'concat',0)"
            ),
            {"now": now},
        )

    with pytest.raises(RuntimeError, match="cannot downgrade workflow tables"):
        command.downgrade(config, "0009_render_job_typed_sources")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0010_video_workflows"
        )
        assert connection.execute(
            text("SELECT program_render_segment_id FROM render_jobs WHERE id='job'")
        ).scalar_one() == "segment"
        assert connection.execute(
            text("SELECT COUNT(*) FROM program_render_segments")
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT COUNT(*) FROM video_workflows")
        ).scalar_one() == 1
