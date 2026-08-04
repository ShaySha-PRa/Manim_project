from collections import deque
from uuid import uuid4

import pytest
from manim_workbench_runner.queue.redis_queue import (
    REDIS_SIGNAL_KEY,
    RedisSignalQueue,
    SignalQueueUnavailable,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: deque[bytes] = deque()
        self.rpush_calls: list[tuple[str, bytes]] = []
        self.blpop_timeouts: list[float] = []

    def rpush(self, key: str, value: bytes) -> int:
        self.rpush_calls.append((key, value))
        self.values.append(value)
        return len(self.values)

    def blpop(self, key: str, timeout: float) -> tuple[bytes, bytes] | None:
        self.blpop_timeouts.append(timeout)
        if not self.values:
            return None
        return key.encode("ascii"), self.values.popleft()


class BrokenRedis:
    def rpush(self, key: str, value: bytes) -> int:
        raise OSError("redis unavailable")

    def blpop(self, key: str, timeout: float) -> tuple[bytes, bytes] | None:
        raise OSError("redis unavailable")


def test_redis_queue_stores_only_uuid_payload_and_claims_with_bound() -> None:
    client = FakeRedis()
    queue = RedisSignalQueue(client)
    job_id = uuid4()

    queue.enqueue(job_id)
    claim = queue.claim(timeout_seconds=0.25)

    assert client.rpush_calls == [(REDIS_SIGNAL_KEY, str(job_id).encode("ascii"))]
    assert client.blpop_timeouts == [0.25]
    assert claim is not None
    assert claim.job_id == job_id
    assert queue.ack(claim) is None


@pytest.mark.parametrize("timeout_seconds", [0, -0.1, 30.1])
def test_redis_queue_rejects_unbounded_or_invalid_claim_timeout(timeout_seconds: float) -> None:
    with pytest.raises(ValueError):
        RedisSignalQueue(FakeRedis()).claim(timeout_seconds=timeout_seconds)


def test_redis_queue_translates_client_unavailability() -> None:
    queue = RedisSignalQueue(BrokenRedis())

    with pytest.raises(SignalQueueUnavailable):
        queue.enqueue(uuid4())
    with pytest.raises(SignalQueueUnavailable):
        queue.claim(timeout_seconds=0.1)


def test_redis_queue_rejects_a_different_redis_key() -> None:
    class WrongKeyRedis(FakeRedis):
        def blpop(self, key: str, timeout: float) -> tuple[bytes, bytes] | None:
            return b"unexpected:key", str(uuid4()).encode("ascii")

    with pytest.raises(SignalQueueUnavailable):
        RedisSignalQueue(WrongKeyRedis()).claim(timeout_seconds=0.1)
