from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, event

DEFAULT_DATABASE_PATH = Path("data/manim_workbench.db")


def database_url() -> str:
    return os.environ.get("MANIM_WORKBENCH_DATABASE_URL", f"sqlite:///{DEFAULT_DATABASE_PATH}")


def configure_sqlite(engine: Engine) -> None:
    if engine.dialect.name != "sqlite" or getattr(engine, "_manim_sqlite_configured", False):
        return

    @event.listens_for(engine, "connect")
    def set_sqlite_pragmas(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    engine._manim_sqlite_configured = True


def create_database_engine(url: str | None = None) -> Engine:
    resolved_url = url or database_url()
    if resolved_url.startswith("sqlite:///./"):
        Path(resolved_url.removeprefix("sqlite:///./")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(resolved_url)
    configure_sqlite(engine)
    return engine
