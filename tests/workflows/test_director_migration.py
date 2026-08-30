from __future__ import annotations

import json
from pathlib import Path

from alembic import command
from manim_workbench_api.database import create_database_engine
from sqlalchemy import inspect, text

from tests.workflows.migration_support import upgrade_workflow_database


def test_0011_adds_director_history_and_preserves_existing_workflow(tmp_path: Path) -> None:
    database_path = tmp_path / "director-migration.db"
    config = upgrade_workflow_database(database_path)
    engine = create_database_engine(f"sqlite:///{database_path}")
    now = "2026-08-31T00:00:00+00:00"
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id,email,created_at) VALUES ('owner','o@test.dev',:now)"),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO projects (id,owner_id,title,created_at) "
                "VALUES ('project','owner','Existing workflow',:now)"
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
                "INSERT INTO video_workflow_versions "
                "(id,workflow_id,project_id,owner_id,version,parent_version_id,"
                "global_brief_json,nodes_json,edges_json,created_at) VALUES "
                "('workflow-v1','workflow','project','owner',1,NULL,:brief,:nodes,:edges,:now)"
            ),
            {
                "brief": json.dumps({"title": "existing"}),
                "nodes": "[]",
                "edges": "[]",
                "now": now,
            },
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_database_engine(f"sqlite:///{database_path}")
    inspector = inspect(engine)
    director_tables = {
        "workflow_director_plans",
        "workflow_director_attempts",
        "workflow_director_events",
    }
    assert director_tables <= set(inspector.get_table_names())
    workflow_columns = {
        column["name"] for column in inspector.get_columns("video_workflow_versions")
    }
    assert {"director_plan_id", "director_edits_json"} <= workflow_columns
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0011_workflow_director"
        )
        assert connection.execute(
            text("SELECT global_brief_json FROM video_workflow_versions WHERE id='workflow-v1'")
        ).scalar_one() == json.dumps({"title": "existing"})
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
        triggers = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='trigger'")
            )
        }
    assert "workflow_director_attempts_prevent_update" in triggers
    assert "workflow_director_attempts_prevent_delete" in triggers
    assert "workflow_director_events_enforce_state_version" in triggers

    engine.dispose()
    command.downgrade(config, "0010_video_workflows")
    engine = create_database_engine(f"sqlite:///{database_path}")
    assert "workflow_director_plans" not in inspect(engine).get_table_names()
    assert "director_plan_id" not in {
        column["name"] for column in inspect(engine).get_columns("video_workflow_versions")
    }
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM video_workflow_versions WHERE id='workflow-v1'")
        ).scalar_one() == 1
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_database_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0011_workflow_director"
        )
