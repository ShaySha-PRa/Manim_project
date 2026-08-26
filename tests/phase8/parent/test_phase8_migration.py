import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[3]


def _config(path: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    return config


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def test_phase8_migration_adds_sessions_rate_limits_and_job_events(tmp_path: Path) -> None:
    path = tmp_path / "phase8.db"
    command.upgrade(_config(path), "0005_phase8")
    connection = sqlite3.connect(path)

    assert {"password_hash", "must_change_password", "disabled_at"} <= _columns(connection, "users")
    assert {"sessions", "login_attempts", "job_events"} <= {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"token_hash", "csrf_token_hash", "expires_at", "revoked_at"} <= _columns(
        connection, "sessions"
    )
    assert {"render_job_id", "owner_id", "state_version", "stage"} <= _columns(
        connection, "job_events"
    )


def test_phase8_migration_downgrades_to_phase7(tmp_path: Path) -> None:
    path = tmp_path / "phase8-down.db"
    config = _config(path)
    command.upgrade(config, "0005_phase8")
    command.downgrade(config, "0004_phase7")
    connection = sqlite3.connect(path)

    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert not {"sessions", "login_attempts", "job_events"} & tables
    assert "password_hash" not in _columns(connection, "users")


def test_phase8_migration_records_durable_job_events(tmp_path: Path) -> None:
    path = tmp_path / "phase8-events.db"
    command.upgrade(_config(path), "0005_phase8")
    connection = sqlite3.connect(path)
    identifiers = {
        "user": "00000000-0000-0000-0000-000000000001",
        "project": "00000000-0000-0000-0000-000000000002",
        "prompt": "00000000-0000-0000-0000-000000000003",
        "plan": "00000000-0000-0000-0000-000000000004",
        "code": "00000000-0000-0000-0000-000000000005",
        "job": "00000000-0000-0000-0000-000000000006",
    }
    now = "2026-08-05T00:00:00+00:00"
    connection.execute(
        "INSERT INTO users (id,email,created_at) VALUES (?,?,?)",
        (identifiers["user"], "owner@example.test", now),
    )
    connection.execute(
        "INSERT INTO projects (id,owner_id,title,created_at) VALUES (?,?,?,?)",
        (identifiers["project"], identifiers["user"], "Project", now),
    )
    connection.execute(
        "INSERT INTO prompt_versions "
        "(id,project_id,owner_id,version,parent_version_id,created_at,prompt) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            identifiers["prompt"],
            identifiers["project"],
            identifiers["user"],
            1,
            None,
            now,
            "prompt",
        ),
    )
    connection.execute(
        "INSERT INTO content_plan_versions "
        "(id,project_id,owner_id,version,parent_version_id,created_at,schema_version,content_json) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            identifiers["plan"],
            identifiers["project"],
            identifiers["user"],
            1,
            None,
            now,
            "1.1",
            "{}",
        ),
    )
    connection.execute(
        "INSERT INTO code_versions "
        "(id,project_id,owner_id,version,parent_version_id,created_at,prompt_version_id,"
        "content_plan_version_id,source_code,source_sha256,scene_class,engine,engine_version) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            identifiers["code"],
            identifiers["project"],
            identifiers["user"],
            1,
            None,
            now,
            identifiers["prompt"],
            identifiers["plan"],
            "pass",
            "0" * 64,
            "GeneratedScene",
            "manimce",
            "0.20.1",
        ),
    )
    connection.execute(
        "INSERT INTO render_jobs "
        "(id,project_id,owner_id,code_version_id,profile,status,idempotency_key,created_at,"
        "attempt_count,state_version) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            identifiers["job"],
            identifiers["project"],
            identifiers["user"],
            identifiers["code"],
            "preview",
            "queued",
            "k" * 16,
            now,
            0,
            0,
        ),
    )
    connection.execute(
        "UPDATE render_jobs SET status='running', state_version=1 WHERE id=?",
        (identifiers["job"],),
    )
    assert connection.execute(
        "SELECT state_version,status,stage FROM job_events ORDER BY id"
    ).fetchall() == [(0, "queued", "preview_render"), (1, "running", "preview_render")]
