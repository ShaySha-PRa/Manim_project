from __future__ import annotations

import json
import os
import re
import shutil
from hashlib import sha256
from pathlib import Path, PurePosixPath
from threading import Lock
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID

from manim_workbench_contracts import (
    RenderArtifactPayload,
    RenderJobCompletion,
    RenderJobFailureCode,
    RenderJobFailureReport,
    RenderJobHeartbeat,
    RenderJobLease,
    RenderJobLeaseRequest,
)

from manim_workbench_runner.quality.orchestration import analyze_published_video
from manim_workbench_runner.queue.types import (
    JobControl,
    LeaseNotActiveError,
    LifecycleUnavailable,
    SandboxCancellationRequested,
    SandboxControlProbe,
    SandboxExecutionError,
    SandboxExecutionResult,
    SandboxWorkItem,
)
from manim_workbench_runner.sandbox import (
    SandboxExecutor,
    SandboxInvocation,
    SandboxLimits,
    memory_tier_for_source,
)
from manim_workbench_runner.sandbox.executor import (
    SandboxExecutionCancelled,
    SandboxExecutionFailure,
    SandboxExecutionSuccess,
)

_ASSET_REF = re.compile(r"/input/assets/([0-9a-f]{64})\.(npz|npy|png)")



class JsonTransport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object]]: ...


class UrllibJsonTransport:
    def __init__(self, *, base_url: str, token: str, timeout_seconds: float = 5.0) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "api"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Phase 5 API must use a private/local HTTP endpoint")
        if not token:
            raise ValueError("internal token is required")
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object]]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self._base_url}{path}",
            data=data,
            method=method,
            headers={"X-Internal-Token": self._token, "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
                return response.status, _json_object(response.read())
        except HTTPError as error:
            return error.code, _json_object(error.read())
        except (OSError, URLError) as error:
            raise LifecycleUnavailable("lifecycle API is unavailable") from error


def _json_object(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("lifecycle API returned invalid JSON") from error
    if not isinstance(value, dict):
        raise RuntimeError("lifecycle API returned a non-object payload")
    return value


class HttpJobLifecycle:
    def __init__(self, transport: JsonTransport) -> None:
        self._transport = transport

    def claim(self, job_id: UUID, *, runner_id: str, lease_seconds: int) -> RenderJobLease | None:
        request = RenderJobLeaseRequest(runner_id=runner_id, lease_seconds=lease_seconds)
        status, payload = self._transport.request(
            "POST", f"/api/v1/internal/render-jobs/{job_id}/claim", request.model_dump(mode="json")
        )
        if status == 409 and _error_code(payload) == "JOB_NOT_CLAIMABLE":
            return None
        _require_success(status, payload)
        return RenderJobLease.model_validate(payload)

    def start(self, lease: RenderJobLease) -> JobControl:
        return self._lease_action(
            lease, "start", RenderJobHeartbeat(lease_token=lease.lease_token, extend_seconds=30)
        )

    def heartbeat(self, lease: RenderJobLease, *, extend_seconds: int) -> JobControl:
        return self._lease_action(
            lease,
            "heartbeat",
            RenderJobHeartbeat(lease_token=lease.lease_token, extend_seconds=extend_seconds),
        )

    def complete(
        self,
        lease: RenderJobLease,
        artifacts: tuple[RenderArtifactPayload, ...],
    ) -> JobControl:
        completion = RenderJobCompletion(lease_token=lease.lease_token, artifacts=artifacts)
        return self._lease_action(lease, "complete", completion)

    def fail(self, lease: RenderJobLease, failure_code: RenderJobFailureCode) -> None:
        report = RenderJobFailureReport(
            lease_token=lease.lease_token,
            failure_code=failure_code,
        )
        control = self._lease_action(lease, "fail", report)
        if control.cancellation_requested:
            self.confirm_cancelled(lease)

    def confirm_cancelled(self, lease: RenderJobLease) -> None:
        status, payload = self._transport.request(
            "POST",
            f"/api/v1/internal/render-jobs/{lease.job_id}/cancelled",
            {"lease_token": lease.lease_token},
        )
        _require_success(status, payload)

    def list_recoverable_job_ids(self) -> tuple[UUID, ...]:
        status, payload = self._transport.request(
            "GET", "/api/v1/internal/render-jobs/recoverable?limit=100"
        )
        _require_success(status, payload)
        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            raise RuntimeError("recoverable response is invalid")
        return tuple(UUID(str(job["id"])) for job in jobs if isinstance(job, dict))

    def _lease_action(self, lease: RenderJobLease, action: str, body: object) -> JobControl:
        payload_body = body.model_dump(mode="json")  # type: ignore[attr-defined]
        status, payload = self._transport.request(
            "POST", f"/api/v1/internal/render-jobs/{lease.job_id}/{action}", payload_body
        )
        if status == 409:
            code = _error_code(payload)
            if code == "CANCELLATION_REQUESTED":
                return JobControl(active=True, cancellation_requested=True)
            if code in {"LEASE_INVALID", "STATE_CONFLICT"}:
                raise LeaseNotActiveError(code)
        _require_success(status, payload)
        cancellation_requested = payload.get("cancellation_requested_at") is not None
        return JobControl(active=True, cancellation_requested=cancellation_requested)


def _error_code(payload: dict[str, object]) -> str | None:
    error = payload.get("error")
    return str(error.get("code")) if isinstance(error, dict) and error.get("code") else None


def _require_success(status: int, payload: dict[str, object]) -> None:
    if not 200 <= status < 300:
        raise RuntimeError(f"lifecycle API rejected request: {_error_code(payload) or status}")


class Phase5SandboxAdapter:
    """Stages a lease payload into narrowly rooted paths and adapts the Docker executor."""

    def __init__(self, *, runtime_root: Path, executor: SandboxExecutor | None = None) -> None:
        runtime_root.mkdir(parents=True, exist_ok=True)
        self._runtime_root = runtime_root.resolve(strict=True)
        self._source_root = self._runtime_root / "sources"
        self._artifact_root = self._runtime_root / "artifacts"
        self._source_root.mkdir(exist_ok=True)
        self._artifact_root.mkdir(exist_ok=True)
        self._executor = executor or SandboxExecutor(
            limits=SandboxLimits(
                allowed_source_root=self._source_root,
                allowed_output_root=self._artifact_root,
            )
        )
        self._active: dict[UUID, SandboxInvocation] = {}
        self._active_lock = Lock()

    def execute(
        self,
        work: SandboxWorkItem,
        *,
        control_probe: SandboxControlProbe,
    ) -> SandboxExecutionResult:
        lease = work.lease
        digest = sha256(lease.source_code.encode("utf-8")).hexdigest()
        if digest != lease.source_sha256:
            raise SandboxExecutionError(RenderJobFailureCode.SANDBOX_SECURITY_VIOLATION)

        source_directory = self._source_root / str(lease.job_id) / f"attempt-{lease.attempt_number}"
        staging = (
            self._artifact_root / ".staging" / str(lease.job_id) / f"attempt-{lease.attempt_number}"
        )
        destination_parent = self._artifact_root / str(lease.job_id)
        destination = destination_parent / f"attempt-{lease.attempt_number}"
        source_directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        staging.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        for path, root in (
            (source_directory.parent, self._source_root),
            (staging.parent, self._artifact_root),
            (destination_parent, self._artifact_root),
        ):
            if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
                raise SandboxExecutionError(RenderJobFailureCode.SANDBOX_SECURITY_VIOLATION)
        source_created = False
        staging_created = False
        try:
            source_directory.mkdir(mode=0o700)
            source_created = True
            staging.mkdir(mode=0o700)
            staging_created = True
        except OSError as error:
            if source_created:
                shutil.rmtree(source_directory, ignore_errors=True)
            if staging_created:
                shutil.rmtree(staging, ignore_errors=True)
            raise SandboxExecutionError(RenderJobFailureCode.SANDBOX_SECURITY_VIOLATION) from error
        source_path = source_directory / "scene.py"
        source_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(source_path, source_flags, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(lease.source_code)
        except OSError as error:
            if source_created:
                shutil.rmtree(source_directory, ignore_errors=True)
            if staging_created:
                shutil.rmtree(staging, ignore_errors=True)
            raise SandboxExecutionError(RenderJobFailureCode.SANDBOX_SECURITY_VIOLATION) from error
        try:
            assets_path = _stage_compute_assets(lease.source_code, source_directory)
        except OSError as error:
            shutil.rmtree(source_directory, ignore_errors=True)
            shutil.rmtree(staging, ignore_errors=True)
            raise SandboxExecutionError(RenderJobFailureCode.SANDBOX_SECURITY_VIOLATION) from error
        invocation = SandboxInvocation(
            job_id=lease.job_id,
            source_path=source_path,
            output_path=staging,
            scene_class=lease.scene_class,
            profile=lease.profile,
            memory_tier=memory_tier_for_source(lease.source_code),
            assets_path=assets_path,
        )
        with self._active_lock:
            self._active[lease.job_id] = invocation
        try:
            result = self._executor.execute(
                invocation,
                publish_directory=destination,
                allowed_publish_root=self._artifact_root,
                control_probe=lambda: _probe_active(control_probe),
            )
            if isinstance(result, SandboxExecutionCancelled):
                raise SandboxCancellationRequested("sandbox execution was cancelled")
            if isinstance(result, SandboxExecutionFailure):
                raise SandboxExecutionError(result.code)
            if not isinstance(result, SandboxExecutionSuccess):
                raise RuntimeError("sandbox returned an unknown result type")
            analyzed_artifacts = analyze_published_video(
                artifact_directory=destination,
                target_duration_seconds=lease.target_duration_seconds,
                artifacts=result.artifacts,
            )
            prefix = PurePosixPath(str(lease.job_id), f"attempt-{lease.attempt_number}")
            artifacts = tuple(
                artifact.model_copy(update={"relative_path": str(prefix / artifact.relative_path)})
                for artifact in analyzed_artifacts
            )
            return SandboxExecutionResult(artifacts=artifacts)
        finally:
            with self._active_lock:
                self._active.pop(lease.job_id, None)
            shutil.rmtree(source_directory, ignore_errors=True)
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    def cancel(self, work: SandboxWorkItem) -> None:
        with self._active_lock:
            invocation = self._active.get(work.lease.job_id)
        if invocation is not None:
            self._executor.cancel(invocation)


def _probe_active(probe: SandboxControlProbe) -> bool:
    control = probe()
    return control.active and not control.cancellation_requested


def _stage_compute_assets(source_code: str, source_directory: Path) -> Path | None:
    needed = list(dict.fromkeys(_ASSET_REF.findall(source_code)))
    if not needed:
        return None
    assets_dir = source_directory / "assets"
    assets_dir.mkdir(mode=0o700)
    search_roots = [
        Path("runtime/compute-artifacts"),
        Path(os.environ.get("MANIM_WORKBENCH_COMPUTE_ROOT", "runtime/compute-artifacts")),
    ]
    catalog: dict[str, Path] = {}
    for root in search_roots:
        if not root.is_dir():
            continue
        for path in root.glob("*.npz"):
            catalog[sha256(path.read_bytes()).hexdigest()] = path
        for path in root.glob("*.npy"):
            catalog[sha256(path.read_bytes()).hexdigest()] = path
        for path in root.glob("*.png"):
            catalog[sha256(path.read_bytes()).hexdigest()] = path
    for digest, suffix in needed:
        source = catalog.get(digest)
        if source is None:
            raise SandboxExecutionError(RenderJobFailureCode.SANDBOX_SECURITY_VIOLATION)
        shutil.copyfile(source, assets_dir / f"{digest}.{suffix}")
    return assets_dir


def build_runtime_components() -> tuple[HttpJobLifecycle, Phase5SandboxAdapter]:
    token = os.environ.get("MANIM_WORKBENCH_INTERNAL_TOKEN", "")
    base_url = os.environ.get("MANIM_WORKBENCH_API_URL", "http://127.0.0.1:8000")
    runtime_root = Path(os.environ.get("MANIM_WORKBENCH_RUNNER_ROOT", "runtime/phase5"))
    return (
        HttpJobLifecycle(UrllibJsonTransport(base_url=base_url, token=token)),
        Phase5SandboxAdapter(runtime_root=runtime_root),
    )
