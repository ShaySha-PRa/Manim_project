"""Storage-level black-box tests for the lossy Redis UUID wake-up contract."""

from __future__ import annotations

from collections import deque
from uuid import UUID, uuid4

import pytest
from manim_workbench_runner.queue.redis_queue import REDIS_SIGNAL_KEY, RedisSignalQueue
from manim_workbench_runner.queue.signals import JobSignalDecodeError


class RecordingRedis:
    def __init__(self) -> None:
        self.values: deque[bytes] = deque()
        self.writes: list[tuple[str, bytes]] = []

    def rpush(self, key: str, value: bytes) -> int:
        self.writes.append((key, value))
        self.values.append(value)
        return len(self.values)

    def blpop(self, key: str, timeout: float) -> tuple[bytes, bytes] | None:
        del timeout
        if not self.values:
            return None
        return key.encode("ascii"), self.values.popleft()


def test_redis_values_contain_only_canonical_uuid_bytes_even_for_duplicate_signals() -> None:
    redis = RecordingRedis()
    queue = RedisSignalQueue(redis)
    job_id = uuid4()

    queue.enqueue(job_id)
    queue.enqueue(job_id)

    assert [key for key, _value in redis.writes] == [REDIS_SIGNAL_KEY, REDIS_SIGNAL_KEY]
    values = [value for _key, value in redis.writes]
    assert values == [str(job_id).encode("ascii"), str(job_id).encode("ascii")]
    assert all(UUID(value.decode("ascii")) == job_id for value in values)
    forbidden = (b"source", b"token", b"/", b"{", b"[")
    assert all(not any(marker in value.lower() for marker in forbidden) for value in values)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"job_id":"00000000-0000-0000-0000-000000000000"}',
        b"00000000-0000-0000-0000-000000000000\n",
        b"00000000-0000-0000-0000-000000000000|lease-token",
        b"not-a-uuid",
    ],
)
def test_redis_payload_confusion_is_rejected_before_it_reaches_runner(payload: bytes) -> None:
    redis = RecordingRedis()
    redis.values.append(payload)

    with pytest.raises(JobSignalDecodeError):
        RedisSignalQueue(redis).claim(timeout_seconds=0.1)


def test_redis_restart_loses_only_signal_not_any_lifecycle_metadata() -> None:
    before_restart = RecordingRedis()
    queue = RedisSignalQueue(before_restart)
    job_id = uuid4()
    queue.enqueue(job_id)

    after_restart = RecordingRedis()
    assert RedisSignalQueue(after_restart).claim(timeout_seconds=0.1) is None
    assert before_restart.writes == [(REDIS_SIGNAL_KEY, str(job_id).encode("ascii"))]
