"""Network-off compute sandbox for allowlisted scientific ops."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manim_workbench_api.tools.kernels import (
    allowed_ops,
    canonical_dumps,
    run_kernel,
    sha256_text,
    write_npz,
)

from manim_workbench_runner.rendering.models import MANIM_IMAGE

DEFAULT_COMPUTE_ROOT = Path("runtime/compute-artifacts")
SANDBOX_USER = "1000:1000"


@dataclass(frozen=True, slots=True)
class ComputeArtifact:
    op: str
    params_sha256: str
    input_sha256: str
    output_sha256: str
    artifact_ref: str
    artifact_path: Path
    assertions: dict[str, float | int | bool | str]
    cache_hit: bool = False


class ComputeSandboxError(RuntimeError):
    """Raised when an unregistered op or sandbox constraint is violated."""


def execute_tool(
    op: str,
    params: Mapping[str, Any],
    *,
    input_text: str | None = None,
    output_root: Path | None = None,
    docker_command: Sequence[str] | None = None,
) -> ComputeArtifact:
    if op not in allowed_ops():
        raise ComputeSandboxError(f"tool op is not allowlisted: {op}")
    params_json = canonical_dumps(dict(params))
    params_sha = sha256_text(params_json)
    input_sha = sha256_text(input_text or "")
    root = output_root or DEFAULT_COMPUTE_ROOT
    root.mkdir(parents=True, exist_ok=True)
    digest_name = sha256_text(f"{op}:{params_sha}:{input_sha}")
    output_path = root / f"{digest_name}.npz"
    if docker_command:
        output_path = _execute_in_docker(
            op,
            params_json,
            input_text,
            root,
            docker_command=docker_command,
        )
        output_sha = hashlib.sha256(output_path.read_bytes()).hexdigest()
        return ComputeArtifact(
            op=op,
            params_sha256=params_sha,
            input_sha256=input_sha,
            output_sha256=output_sha,
            artifact_ref=f"tool:{op}:{output_sha[:16]}",
            artifact_path=output_path,
            assertions=_load_assertions(output_path),
        )
    if output_path.is_file():
        output_sha = hashlib.sha256(output_path.read_bytes()).hexdigest()
        return ComputeArtifact(
            op=op,
            params_sha256=params_sha,
            input_sha256=input_sha,
            output_sha256=output_sha,
            artifact_ref=f"tool:{op}:{output_sha[:16]}",
            artifact_path=output_path,
            assertions=_load_assertions(output_path),
            cache_hit=True,
        )
    result = run_kernel(op, params, input_text)
    output_sha = write_npz(output_path, result)
    return ComputeArtifact(
        op=op,
        params_sha256=params_sha,
        input_sha256=input_sha,
        output_sha256=output_sha,
        artifact_ref=f"tool:{op}:{output_sha[:16]}",
        artifact_path=output_path,
        assertions=result.assertions,
    )


def _load_assertions(path: Path) -> dict[str, float | int | bool | str]:
    import numpy as np

    packed = np.load(path, allow_pickle=False)
    raw = packed["assertion_json"]
    text = raw.item() if getattr(raw, "shape", ()) == () else str(raw)
    return json.loads(str(text))


def _execute_in_docker(
    op: str,
    params_json: str,
    input_text: str | None,
    output_root: Path,
    *,
    docker_command: Sequence[str],
) -> Path:
    import subprocess
    import tempfile

    work = Path(tempfile.mkdtemp(prefix="compute-"))
    (work / "params.json").write_text(params_json, encoding="utf-8")
    (work / "input.txt").write_text(input_text or "", encoding="utf-8")
    output_dir = work / "output"
    output_dir.mkdir()
    entry = Path(__file__).with_name("compute_entry.py")
    kernels = (
        Path(__file__).resolve().parents[4]
        / "api"
        / "src"
        / "manim_workbench_api"
        / "tools"
        / "kernels.py"
    )
    command = (
        *docker_command,
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        SANDBOX_USER,
        "--pids-limit",
        "32",
        "--memory",
        "1g",
        "--cpus",
        "1.0",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=128m",
        "--volume",
        f"{entry}:/input/compute_entry.py:ro",
        "--volume",
        f"{kernels}:/input/kernels.py:ro",
        "--volume",
        f"{work / 'params.json'}:/input/params.json:ro",
        "--volume",
        f"{work / 'input.txt'}:/input/input.txt:ro",
        "--volume",
        f"{output_dir}:/output:rw",
        "--workdir",
        "/input",
        "--entrypoint",
        "python",
        MANIM_IMAGE,
        "/input/compute_entry.py",
        op,
    )
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise ComputeSandboxError((completed.stdout or "") + (completed.stderr or ""))
    produced = list(output_dir.glob("*.npz"))
    if len(produced) != 1:
        raise ComputeSandboxError("compute sandbox did not produce one npz")
    final_path = output_root / produced[0].name
    final_path.write_bytes(produced[0].read_bytes())
    return final_path
