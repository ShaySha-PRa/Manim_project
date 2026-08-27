import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_phase10_migration_adds_assets_and_allows_021(tmp_path: Path) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    db = tmp_path / "ir.db"
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    command.upgrade(config, "0008_asset_versions")
    import sqlite3

    connection = sqlite3.connect(db)
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "user_assets" in tables
    assert "asset_versions" in tables
    columns = {row[1] for row in connection.execute("PRAGMA table_info(render_jobs)")}
    assert {"concat_group_id", "segment_index"} <= columns


def test_phase10_migration_rebuilds_parent_tables_with_existing_render_job(
    tmp_path: Path,
) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    db = tmp_path / "populated-ir.db"
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    command.upgrade(config, "0006_phase9")
    connection = sqlite3.connect(db)
    connection.execute("PRAGMA foreign_keys=ON")
    now = "2026-08-27T00:00:00+00:00"
    owner_id = "00000000-0000-0000-0000-000000000001"
    project_id = "10000000-0000-0000-0000-000000000001"
    prompt_id = "20000000-0000-0000-0000-000000000001"
    plan_id = "30000000-0000-0000-0000-000000000001"
    code_id = "40000000-0000-0000-0000-000000000001"
    job_id = "50000000-0000-0000-0000-000000000001"
    connection.execute(
        "INSERT INTO users (id,email,created_at) VALUES (?,?,?)",
        (owner_id, "migration-owner@example.test", now),
    )
    connection.execute(
        "INSERT INTO projects (id,owner_id,title,created_at,updated_at) VALUES (?,?,?,?,?)",
        (project_id, owner_id, "Existing project", now, now),
    )
    connection.execute(
        "INSERT INTO prompt_versions "
        "(id,project_id,owner_id,version,parent_version_id,created_at,prompt) "
        "VALUES (?,?,?,1,NULL,?,?)",
        (prompt_id, project_id, owner_id, now, "Existing prompt"),
    )
    connection.execute(
        "INSERT INTO content_plan_versions "
        "(id,project_id,owner_id,version,parent_version_id,created_at,schema_version,"
        "content_json) VALUES (?,?,?,1,NULL,?,'1.1','{}')",
        (plan_id, project_id, owner_id, now),
    )
    connection.execute(
        "INSERT INTO code_versions "
        "(id,project_id,owner_id,version,parent_version_id,created_at,prompt_version_id,"
        "content_plan_version_id,source_code,source_sha256,engine,engine_version,scene_class,"
        "category,generation_mode,assumptions_json) VALUES "
        "(?,?,?,1,NULL,?,?,?,'pass',?,'manimce','0.20.1','GeneratedScene',"
        "'formula_derivation','full','[]')",
        (code_id, project_id, owner_id, now, prompt_id, plan_id, "a" * 64),
    )
    connection.execute(
        "INSERT INTO render_jobs "
        "(id,project_id,owner_id,code_version_id,profile,status,idempotency_key,created_at) "
        "VALUES (?,?,?,?,'preview','queued','existing-job',?)",
        (job_id, project_id, owner_id, code_id, now),
    )
    connection.commit()
    connection.close()

    command.upgrade(config, "0008_asset_versions")

    migrated = sqlite3.connect(db)
    assert migrated.execute("SELECT version_num FROM alembic_version").fetchone() == (
        "0008_asset_versions",
    )
    assert migrated.execute(
        "SELECT code_version_id FROM render_jobs WHERE id=?", (job_id,)
    ).fetchone() == (code_id,)
    assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []
    assert migrated.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '_alembic_tmp_%'"
    ).fetchall() == []
