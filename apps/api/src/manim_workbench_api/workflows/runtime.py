"""API-side lossy Redis notifier for already committed workflow tasks."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Protocol
from uuid import UUID

from redis import Redis
from redis.exceptions import RedisError

from .queue import WorkflowTaskKind
from .signals import WORKFLOW_SIGNAL_KEYS, encode_workflow_signal


class RedisPushClient(Protocol):
    def rpush(self, key: str, value: bytes) -> int: ...


class RedisWorkflowTaskNotifier:
    """Wake the Runner on a task-kind-specific channel without publishing task data."""

    def __init__(self, client: RedisPushClient) -> None:
        self._client = client

    def wake(self, kind: WorkflowTaskKind, task_id: UUID) -> None:
        if not isinstance(kind, WorkflowTaskKind):
            raise TypeError("workflow signal kind is invalid")
        try:
            self._client.rpush(
                WORKFLOW_SIGNAL_KEYS[kind.value], encode_workflow_signal(task_id)
            )
        except (OSError, RedisError) as error:
            # WorkflowTaskQueue treats notifier OSError as lossy wake-up failure. The
            # committed SQLite task remains recoverable by the Runner's periodic scan.
            raise OSError("workflow Redis wake-up is unavailable") from error


@lru_cache(maxsize=1)
def get_redis_workflow_task_notifier() -> RedisWorkflowTaskNotifier:
    client = Redis.from_url(
        os.environ.get("MANIM_WORKBENCH_REDIS_URL", "redis://127.0.0.1:6379/0"),
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
        retry_on_timeout=False,
        decode_responses=False,
    )
    return RedisWorkflowTaskNotifier(client)
