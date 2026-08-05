from __future__ import annotations

import os
from functools import lru_cache
from typing import Protocol
from uuid import UUID

from redis import Redis
from redis.exceptions import RedisError

from manim_workbench_api.jobs.dependencies import JobSignalUnavailable

REDIS_SIGNAL_KEY = "manim-workbench:phase5:render-jobs"


class RedisPushClient(Protocol):
    def rpush(self, key: str, value: bytes) -> int: ...


class RedisJobSignalPublisher:
    """API-side adapter that publishes only the committed Job UUID."""

    def __init__(self, client: RedisPushClient) -> None:
        self._client = client

    def publish(self, job_id: UUID) -> None:
        if not isinstance(job_id, UUID):
            raise TypeError("job_id must be a UUID")
        try:
            self._client.rpush(REDIS_SIGNAL_KEY, str(job_id).encode("ascii"))
        except (OSError, RedisError) as error:
            raise JobSignalUnavailable("Redis wake-up signal is unavailable") from error


@lru_cache(maxsize=1)
def get_redis_job_signal_publisher() -> RedisJobSignalPublisher:
    redis_url = os.environ.get("MANIM_WORKBENCH_REDIS_URL", "redis://127.0.0.1:6379/0")
    client = Redis.from_url(
        redis_url,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
        retry_on_timeout=False,
        decode_responses=False,
    )
    return RedisJobSignalPublisher(client)
