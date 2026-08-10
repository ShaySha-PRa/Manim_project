from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy.engine import make_url

_ACCEPTANCE_ROOT_VARIABLE = "MANIM_WORKBENCH_ACCEPTANCE_ROOT"
_DATABASE_URL_VARIABLE = "MANIM_WORKBENCH_DATABASE_URL"
_original_set_main_option = Config.set_main_option
_installed = False


def _sqlite_path(raw_url: str) -> Path | None:
    url = make_url(raw_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return None
    path = Path(url.database)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def pytest_configure(config: Any) -> None:
    """Keep explicit pytest temp DBs while retaining the safe acceptance URL in the env."""

    global _installed
    if _installed:
        return
    acceptance_root_value = os.environ.get(_ACCEPTANCE_ROOT_VARIABLE)
    safe_url = os.environ.get(_DATABASE_URL_VARIABLE)
    if not acceptance_root_value or not safe_url:
        raise pytest.UsageError("Milestone 1 acceptance database boundary is missing.")
    acceptance_root = Path(acceptance_root_value).resolve()
    safe_database = _sqlite_path(safe_url)
    if safe_database is None or not _is_within(safe_database, acceptance_root):
        raise pytest.UsageError("Milestone 1 acceptance database must be temporary SQLite.")

    def guarded_set_main_option(self: Config, name: str, value: str) -> None:
        if name == "sqlalchemy.url" and value == safe_url:
            configured_database = _sqlite_path(self.get_main_option(name))
            if configured_database is not None and _is_within(
                configured_database, acceptance_root
            ):
                return
        _original_set_main_option(self, name, value)

    Config.set_main_option = guarded_set_main_option  # type: ignore[method-assign]
    _installed = True


def pytest_unconfigure(config: Any) -> None:
    global _installed
    if _installed:
        Config.set_main_option = _original_set_main_option  # type: ignore[method-assign]
        _installed = False
