from __future__ import annotations

from collections import deque

import pytest
from manim_workbench_runner.queue.coordinator import CoordinatorOutcome
from manim_workbench_runner.queue.types import LifecycleUnavailable


class IntermittentCoordinator:
    def __init__(self) -> None:
        self.run_results: deque[object] = deque(
            [
                LifecycleUnavailable("api restarting"),
                CoordinatorOutcome.IDLE,
                KeyboardInterrupt(),
            ]
        )
        self.recover_calls = 0
        self.run_calls = 0

    def recover(self) -> object:
        self.recover_calls += 1
        raise LifecycleUnavailable("api starting")

    def run_once(self, *, timeout_seconds: float) -> CoordinatorOutcome:
        assert timeout_seconds == 5.0
        self.run_calls += 1
        result = self.run_results.popleft()
        if isinstance(result, BaseException):
            raise result
        assert isinstance(result, CoordinatorOutcome)
        return result


def test_worker_survives_api_restart_and_resumes_polling(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from manim_workbench_runner.__main__ import _serve_coordinator

    coordinator = IntermittentCoordinator()
    sleeps: list[float] = []

    with pytest.raises(KeyboardInterrupt):
        _serve_coordinator(
            coordinator,  # type: ignore[arg-type]
            once=False,
            sleep=sleeps.append,
        )

    output = capsys.readouterr().out
    assert coordinator.recover_calls == 1
    assert coordinator.run_calls == 3
    assert sleeps == [1.0]
    assert output.count('"event":"api_unavailable"') == 2
    assert '"outcome":"idle"' in output
