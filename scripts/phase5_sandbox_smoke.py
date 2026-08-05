#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from manim_workbench_contracts import RenderJobLease, RenderProfile
from manim_workbench_runner.phase5_runtime import Phase5SandboxAdapter
from manim_workbench_runner.queue.types import (
    JobControl,
    SandboxCancellationRequested,
    SandboxWorkItem,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one real Phase 5 sandbox smoke render")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--scene-class", required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--target-duration", type=float, default=10.0)
    parser.add_argument("--profile", choices=("preview", "final"), default="preview")
    parser.add_argument("--cancel-after-probes", type=int)
    arguments = parser.parse_args()

    source = arguments.source.resolve(strict=True).read_text(encoding="utf-8")
    job_id = uuid4()
    lease = RenderJobLease(
        job_id=job_id,
        code_version_id=uuid4(),
        content_plan_version_id=uuid4(),
        target_duration_seconds=arguments.target_duration,
        profile=RenderProfile(arguments.profile),
        scene_class=arguments.scene_class,
        source_code=source,
        source_sha256=sha256(source.encode("utf-8")).hexdigest(),
        lease_token="a" * 64,
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        attempt_number=1,
    )
    probe_count = 0

    def control_probe() -> JobControl:
        nonlocal probe_count
        probe_count += 1
        requested = (
            arguments.cancel_after_probes is not None
            and probe_count >= arguments.cancel_after_probes
        )
        return JobControl(active=True, cancellation_requested=requested)

    try:
        result = Phase5SandboxAdapter(runtime_root=arguments.runtime_root).execute(
            SandboxWorkItem(lease),
            control_probe=control_probe,
        )
    except SandboxCancellationRequested:
        if arguments.cancel_after_probes is None:
            raise
        print(json.dumps({"job_id": str(job_id), "cancelled": True, "probes": probe_count}))
        return 0
    if arguments.cancel_after_probes is not None:
        raise RuntimeError("sandbox completed before the requested cancellation")
    print(
        json.dumps(
            {
                "job_id": str(job_id),
                "artifacts": [artifact.model_dump(mode="json") for artifact in result.artifacts],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
