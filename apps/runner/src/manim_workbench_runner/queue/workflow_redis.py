"""Lossy Redis wake-ups plus authoritative SQLite scanning for workflow tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from manim_workbench_api.workflows import WorkflowTaskKind
from manim_workbench_api.workflows.signals import (
    WORKFLOW_SIGNAL_KEYS,
    decode_workflow_signal,
)
from redis.exceptions import RedisError

from .workflow_coordinator import (
    WorkflowCoordinatorOutcome,
    WorkflowTaskCoordinator,
)


class RedisWorkflowListClient(Protocol):
    def blpop(
        self, keys: list[str], timeout: float
    ) -> tuple[bytes, bytes] | None: ...


@dataclass(frozen=True, slots=True)
class WorkflowWakeSignal:
    kind: WorkflowTaskKind
    task_id: UUID


class WorkflowSignalQueueUnavailable(RuntimeError):
    pass


class RedisWorkflowSignalQueue:
    def __init__(self, client: RedisWorkflowListClient) -> None:
        self._client = client

    def claim(self, *, timeout_seconds: float) -> WorkflowWakeSignal | None:
        if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 30:
            raise ValueError("workflow signal timeout must be within (0, 30]")
        keys = list(WORKFLOW_SIGNAL_KEYS.values())
        try:
            result = self._client.blpop(keys, timeout=timeout_seconds)
        except (OSError, RedisError) as error:
            raise WorkflowSignalQueueUnavailable(
                "workflow Redis claim failed"
            ) from error
        if result is None:
            return None
        raw_key, payload = result
        try:
            key = raw_key.decode("ascii")
        except (AttributeError, UnicodeDecodeError) as error:
            raise ValueError("workflow Redis returned an invalid key") from error
        kinds = {value: WorkflowTaskKind(kind) for kind, value in WORKFLOW_SIGNAL_KEYS.items()}
        if key not in kinds:
            raise ValueError("workflow Redis returned an unexpected key")
        return WorkflowWakeSignal(
            kind=kinds[key],
            task_id=decode_workflow_signal(payload),
        )


class PersistentWorkflowWorker:
    """Use Redis only for latency; scan both durable task kinds on every idle/error pass."""

    def __init__(
        self,
        signals: RedisWorkflowSignalQueue,
        coordinator: WorkflowTaskCoordinator,
    ) -> None:
        self._signals = signals
        self._coordinator = coordinator

    def run_once(self, *, timeout_seconds: float) -> WorkflowCoordinatorOutcome:
        try:
            signal = self._signals.claim(timeout_seconds=timeout_seconds)
        except (WorkflowSignalQueueUnavailable, ValueError):
            signal = None
        ordered = [WorkflowTaskKind.SCENE_PROGRAM, WorkflowTaskKind.COMPOSITION]
        if signal is not None:
            ordered.remove(signal.kind)
            ordered.insert(0, signal.kind)
        for kind in ordered:
            outcome = self._coordinator.run_once(kind.value)
            if outcome is not WorkflowCoordinatorOutcome.IDLE:
                return outcome
        return WorkflowCoordinatorOutcome.IDLE
