import argparse
import json
import os
import re
import socket
from collections.abc import Callable
from time import sleep as default_sleep

from manim_workbench_contracts import CONTRACT_SCHEMA_VERSION
from redis import Redis

from manim_workbench_runner.phase5_runtime import build_runtime_components
from manim_workbench_runner.queue import RedisSignalQueue, RunnerCoordinator
from manim_workbench_runner.queue.types import LifecycleUnavailable
from manim_workbench_runner.workflow_runtime import build_workflow_worker


def _print_idle() -> None:
    print(
        json.dumps(
            {
                "status": "idle",
                "service": "runner",
                "contract_schema_version": CONTRACT_SCHEMA_VERSION,
                "docker_access": False,
            },
            separators=(",", ":"),
        )
    )


def _runner_id() -> str:
    configured = os.environ.get("MANIM_WORKBENCH_RUNNER_ID")
    candidate = configured or f"runner-{socket.gethostname()}"
    normalized = re.sub(r"[^A-Za-z0-9_.-]", "-", candidate)[:100]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,99}", normalized):
        raise ValueError("MANIM_WORKBENCH_RUNNER_ID is invalid")
    return normalized


def _run_worker(*, once: bool) -> None:
    redis_url = os.environ.get("MANIM_WORKBENCH_REDIS_URL", "redis://127.0.0.1:6379/0")
    redis_client = Redis.from_url(
        redis_url,
        socket_connect_timeout=1.0,
        socket_timeout=35.0,
        retry_on_timeout=False,
        decode_responses=False,
    )
    lifecycle, sandbox = build_runtime_components()
    coordinator = RunnerCoordinator(
        queue=RedisSignalQueue(redis_client),
        lifecycle=lifecycle,
        sandbox=sandbox,
        runner_id=_runner_id(),
    )
    workflow_worker = build_workflow_worker(redis_client, runner_id=_runner_id())
    _serve_coordinator(coordinator, workflow_worker=workflow_worker, once=once)


def _serve_coordinator(
    coordinator: RunnerCoordinator,
    *,
    workflow_worker=None,  # type: ignore[no-untyped-def]
    once: bool,
    sleep: Callable[[float], None] = default_sleep,
) -> None:
    try:
        recovery = coordinator.recover()
    except LifecycleUnavailable:
        _print_event("api_unavailable")
    else:
        print(json.dumps({
            "event": "recovery_complete",
            "signaled": len(recovery.signaled_job_ids),
            "failed": len(recovery.failed_job_ids),
        }, separators=(",", ":")))
    while True:
        try:
            outcome = coordinator.run_once(
                timeout_seconds=1.0 if once or workflow_worker is not None else 5.0
            )
        except LifecycleUnavailable:
            _print_event("api_unavailable")
            if once:
                return
            sleep(1.0)
            continue
        print(
            json.dumps(
                {"event": "runner_outcome", "outcome": outcome.value}, separators=(",", ":")
            )
        )
        if workflow_worker is not None:
            workflow_outcome = workflow_worker.run_once(
                timeout_seconds=0.1 if once else 1.0
            )
            print(
                json.dumps(
                    {
                        "event": "workflow_runner_outcome",
                        "outcome": workflow_outcome.value,
                    },
                    separators=(",", ":"),
                )
            )
        if once:
            return


def _print_event(event: str) -> None:
    print(json.dumps({"event": event}, separators=(",", ":")))


def main() -> None:
    parser = argparse.ArgumentParser(description="Manim Workbench host Runner")
    subparsers = parser.add_subparsers(dest="command")
    run_parser = subparsers.add_parser("run", help="start the Phase 5 host worker")
    run_parser.add_argument("--once", action="store_true", help="process at most one signal")
    arguments = parser.parse_args()
    if arguments.command != "run":
        _print_idle()
        return
    try:
        _run_worker(once=arguments.once)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
