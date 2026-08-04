from __future__ import annotations

import os
import secrets
from typing import Protocol
from uuid import UUID

from sqlalchemy import Engine

from manim_workbench_api.database import create_database_engine


class JobSignalPublisher(Protocol):
    """Best-effort wake-up signal publisher; SQLite remains the source of truth."""

    def publish(self, job_id: UUID) -> None:
        """Publish only a Job UUID after its SQLite transaction has committed."""


class NullJobSignalPublisher:
    """Safe default until the parent agent wires the Runner-owned Redis adapter."""

    def publish(self, job_id: UUID) -> None:
        del job_id


def get_database_engine() -> Engine:
    return create_database_engine()


def get_job_signal_publisher() -> JobSignalPublisher:
    return NullJobSignalPublisher()


def get_internal_token() -> str:
    return os.environ.get("MANIM_WORKBENCH_INTERNAL_TOKEN", "")


def internal_token_is_valid(provided: str | None, expected: str) -> bool:
    """Compare an environment token without exposing either value."""
    return bool(expected) and bool(provided) and secrets.compare_digest(provided, expected)
