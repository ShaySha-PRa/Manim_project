"""A Redis list adapter that stores only canonical render-job UUID signals."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from redis.exceptions import RedisError

from .signals import JobSignalDecodeError, decode_job_signal, encode_job_signal
from .types import ClaimedSignal

REDIS_SIGNAL_KEY = "manim-workbench:phase5:render-jobs"
MAX_CLAIM_TIMEOUT_SECONDS = 30.0


class RedisListClient(Protocol):
    def rpush(self, key: str, value: bytes) -> int: ...

    def blpop(self, key: str, timeout: float) -> tuple[bytes, bytes] | None: ...


class SignalQueueUnavailable(RuntimeError):
    """A bounded Redis operation could not reach the signal queue."""


class RedisSignalQueue:
    """Destructive BLPOP queue; SQLite recovery re-signals work after a Runner crash.

    BLPOP removes a signal before returning it, so ``ack`` intentionally has no Redis
    side effect.  The coordinator still calls it on every terminal handling path, which
    keeps this port compatible with an explicit-ack implementation in the future.
    """

    def __init__(self, client: RedisListClient) -> None:
        self._client = client

    def enqueue(self, job_id: UUID) -> None:
        try:
            self._client.rpush(REDIS_SIGNAL_KEY, encode_job_signal(job_id))
        except (OSError, RedisError) as error:
            raise SignalQueueUnavailable("Redis enqueue failed") from error

    def claim(self, *, timeout_seconds: float) -> ClaimedSignal | None:
        _validate_claim_timeout(timeout_seconds)
        try:
            result = self._client.blpop(REDIS_SIGNAL_KEY, timeout=timeout_seconds)
        except (OSError, RedisError) as error:
            raise SignalQueueUnavailable("Redis claim failed") from error

        if result is None:
            return None
        key, payload = result
        if key != REDIS_SIGNAL_KEY.encode("ascii"):
            raise SignalQueueUnavailable("Redis returned a signal from an unexpected key")
        try:
            return ClaimedSignal(job_id=decode_job_signal(payload))
        except JobSignalDecodeError:
            raise
        except TypeError as error:
            raise JobSignalDecodeError("Redis job signal must be bytes") from error

    def ack(self, claim: ClaimedSignal) -> None:
        """Acknowledge an already destructive BLPOP claim without writing any metadata."""
        del claim


def _validate_claim_timeout(timeout_seconds: float) -> None:
    if type(timeout_seconds) not in (int, float):
        raise ValueError("claim timeout must be a finite number of seconds")
    if not 0 < float(timeout_seconds) <= MAX_CLAIM_TIMEOUT_SECONDS:
        raise ValueError(f"claim timeout must be within (0, {MAX_CLAIM_TIMEOUT_SECONDS}]")
