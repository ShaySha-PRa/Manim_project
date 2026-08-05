from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from manim_workbench_contracts import RenderArtifactPayload, RenderJobLease, RenderProfile
from manim_workbench_contracts.models import ArtifactKind


def _lease(source: str = "from manim import Scene\n") -> RenderJobLease:
    return RenderJobLease(
        job_id=uuid4(),
        code_version_id=uuid4(),
        content_plan_version_id=uuid4(),
        target_duration_seconds=10,
        profile=RenderProfile.PREVIEW,
        scene_class="GeneratedScene",
        source_code=source,
        source_sha256=sha256(source.encode()).hexdigest(),
        lease_token="a" * 64,
        lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        attempt_number=1,
    )


def test_main_mounts_phase5_router() -> None:
    from manim_workbench_api.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/v1/render-jobs" in paths
    assert "/api/v1/internal/render-jobs/recoverable" in paths


def test_redis_publisher_maps_only_expected_outage() -> None:
    from manim_workbench_api.jobs.dependencies import JobSignalUnavailable
    from manim_workbench_api.phase5_runtime import RedisJobSignalPublisher
    from redis.exceptions import ConnectionError

    class Client:
        def rpush(self, _key: str, _value: bytes) -> int:
            raise ConnectionError("offline")

    with pytest.raises(JobSignalUnavailable):
        RedisJobSignalPublisher(Client()).publish(uuid4())


def test_api_and_runner_share_exact_signal_namespace() -> None:
    from manim_workbench_api.phase5_runtime import REDIS_SIGNAL_KEY as api_key
    from manim_workbench_runner.queue.redis_queue import REDIS_SIGNAL_KEY as runner_key

    assert api_key == runner_key


def test_http_lifecycle_claim_parses_embedded_work_item() -> None:
    from manim_workbench_runner.phase5_runtime import HttpJobLifecycle

    lease = _lease()

    class Transport:
        def request(self, method: str, path: str, payload: dict[str, object] | None = None):
            assert method == "POST"
            assert path == f"/api/v1/internal/render-jobs/{lease.job_id}/claim"
            assert payload == {"runner_id": "runner-01", "lease_seconds": 30}
            return 200, lease.model_dump(mode="json")

    lifecycle = HttpJobLifecycle(Transport())
    assert lifecycle.claim(lease.job_id, runner_id="runner-01", lease_seconds=30) == lease


def test_http_transport_rejects_lookalike_local_hostname() -> None:
    from manim_workbench_runner.phase5_runtime import UrllibJsonTransport

    with pytest.raises(ValueError, match="private/local"):
        UrllibJsonTransport(base_url="http://localhost.evil.example:8000", token="token")


def test_sandbox_adapter_verifies_source_and_rewrites_published_paths(tmp_path: Path) -> None:
    from manim_workbench_runner.phase5_runtime import Phase5SandboxAdapter
    from manim_workbench_runner.queue.types import JobControl, SandboxWorkItem
    from manim_workbench_runner.sandbox.executor import SandboxExecutionSuccess

    lease = _lease()
    artifacts = tuple(
        RenderArtifactPayload(kind=kind, relative_path=name, sha256="b" * 64, byte_size=1)
        for kind, name in (
            (ArtifactKind.VIDEO, "video.mp4"),
            (ArtifactKind.THUMBNAIL, "thumbnail.jpg"),
            (ArtifactKind.RENDER_LOG, "render.log"),
            (ArtifactKind.METADATA, "metadata.json"),
        )
    )

    class Executor:
        def execute(self, invocation, **kwargs):  # type: ignore[no-untyped-def]
            assert invocation.source_path.read_text(encoding="utf-8") == lease.source_code
            assert kwargs["control_probe"]() is True
            published = kwargs["publish_directory"]
            published.mkdir(parents=True)
            (published / "video.mp4").write_bytes(b"invalid-test-video")
            (published / "thumbnail.jpg").write_bytes(b"thumbnail")
            (published / "render.log").write_text("ok", encoding="utf-8")
            (published / "metadata.json").write_text("{}\n", encoding="utf-8")
            return SandboxExecutionSuccess(True, "container", 0.1, artifacts)

        def cancel(self, invocation):  # type: ignore[no-untyped-def]
            del invocation

    adapter = Phase5SandboxAdapter(runtime_root=tmp_path, executor=Executor())
    result = adapter.execute(
        SandboxWorkItem(lease),
        control_probe=lambda: JobControl(active=True, cancellation_requested=False),
    )

    assert {artifact.relative_path for artifact in result.artifacts} == {
        f"{lease.job_id}/attempt-1/{name}"
        for name in ("video.mp4", "thumbnail.jpg", "render.log", "metadata.json")
    }


def test_sandbox_adapter_rejects_source_hash_mismatch(tmp_path: Path) -> None:
    from manim_workbench_runner.phase5_runtime import Phase5SandboxAdapter
    from manim_workbench_runner.queue.types import JobControl, SandboxWorkItem

    lease = _lease().model_copy(update={"source_sha256": "0" * 64})
    adapter = Phase5SandboxAdapter(runtime_root=tmp_path)
    from manim_workbench_runner.queue.types import SandboxExecutionError

    with pytest.raises(SandboxExecutionError):
        adapter.execute(
            SandboxWorkItem(lease),
            control_probe=lambda: JobControl(active=True, cancellation_requested=False),
        )


def test_sandbox_adapter_refuses_preexisting_attempt_staging(tmp_path: Path) -> None:
    from manim_workbench_runner.phase5_runtime import Phase5SandboxAdapter
    from manim_workbench_runner.queue.types import (
        JobControl,
        SandboxExecutionError,
        SandboxWorkItem,
    )

    lease = _lease()
    adapter = Phase5SandboxAdapter(runtime_root=tmp_path)
    planted = tmp_path / "sources" / str(lease.job_id) / "attempt-1"
    planted.mkdir(parents=True)
    (planted / "scene.py").symlink_to("/etc/passwd")

    with pytest.raises(SandboxExecutionError):
        adapter.execute(
            SandboxWorkItem(lease),
            control_probe=lambda: JobControl(active=True, cancellation_requested=False),
        )


def test_sandbox_adapter_does_not_follow_planted_parent_symlink(tmp_path: Path) -> None:
    from manim_workbench_runner.phase5_runtime import Phase5SandboxAdapter
    from manim_workbench_runner.queue.types import (
        JobControl,
        SandboxExecutionError,
        SandboxWorkItem,
    )

    lease = _lease()
    adapter = Phase5SandboxAdapter(runtime_root=tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "sources" / str(lease.job_id)).symlink_to(outside)

    with pytest.raises(SandboxExecutionError):
        adapter.execute(
            SandboxWorkItem(lease),
            control_probe=lambda: JobControl(active=True, cancellation_requested=False),
        )
    assert not (outside / "attempt-1" / "scene.py").exists()
