from pathlib import Path
from uuid import uuid4

import pytest
from manim_workbench_contracts import RenderProfile


def test_api_job_router_freezes_public_and_internal_paths() -> None:
    from manim_workbench_api.jobs.router import router

    routes = {(route.path, method) for route in router.routes for method in route.methods}
    assert ("/render-jobs", "POST") in routes
    assert ("/render-jobs/{job_id}", "GET") in routes
    assert ("/render-jobs/{job_id}/cancel", "POST") in routes
    assert ("/internal/render-jobs/{job_id}/claim", "POST") in routes
    assert ("/internal/render-jobs/{job_id}/heartbeat", "POST") in routes
    assert ("/internal/render-jobs/{job_id}/start", "POST") in routes
    assert ("/internal/render-jobs/{job_id}/complete", "POST") in routes
    assert ("/internal/render-jobs/{job_id}/fail", "POST") in routes


def test_redis_signal_codec_accepts_only_one_uuid() -> None:
    from manim_workbench_runner.queue.signals import decode_job_signal, encode_job_signal

    job_id = uuid4()
    assert encode_job_signal(job_id) == str(job_id).encode("ascii")
    assert decode_job_signal(encode_job_signal(job_id)) == job_id
    with pytest.raises(ValueError):
        decode_job_signal(b'{"job_id":"00000000-0000-0000-0000-000000000000","code":"x"}')


def test_sandbox_command_is_fail_closed(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.policy import (
        SandboxInvocation,
        SandboxLimits,
        build_sandbox_command,
    )

    source = tmp_path / "scene.py"
    source.write_text("from manim import Scene\n", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    invocation = SandboxInvocation(uuid4(), source, output, "GeneratedScene", RenderProfile.PREVIEW)
    command = build_sandbox_command(invocation, SandboxLimits())
    joined = " ".join(command)

    for required in (
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--pids-limit",
        "--memory",
        "--cpus",
        "--tmpfs /tmp:",
        ":/input/scene.py:ro",
        ":/output:rw",
    ):
        assert required in joined
    assert "--privileged" not in command
    assert "/var/run/docker.sock" not in joined
