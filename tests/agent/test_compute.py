from pathlib import Path

from manim_workbench_runner.sandbox.compute_runtime import ComputeSandboxError, execute_tool


def test_compute_rejects_unregistered_ops(tmp_path: Path) -> None:
    try:
        execute_tool("os.system", {}, output_root=tmp_path)
    except ComputeSandboxError as error:
        assert "allowlisted" in str(error)
    else:
        raise AssertionError("unregistered ops must fail closed")


def test_wave_artifact_is_npz_without_pickle(tmp_path: Path) -> None:
    import numpy as np

    artifact = execute_tool(
        "wave2d_superposition",
        {"c": 1.15, "k": 6.2, "nx": 24, "ny": 24, "nt": 8},
        output_root=tmp_path,
    )
    packed = np.load(artifact.artifact_path, allow_pickle=False)
    assert packed["rgb"].ndim == 4
    assert artifact.assertions["linear_superposition"] is True
    assert artifact.output_sha256 == artifact.output_sha256.lower()
    assert artifact.cache_hit is False
    cached = execute_tool(
        "wave2d_superposition",
        {"c": 1.15, "k": 6.2, "nx": 24, "ny": 24, "nt": 8},
        output_root=tmp_path,
    )
    assert cached.cache_hit is True
    assert cached.output_sha256 == artifact.output_sha256
    assert cached.artifact_path == artifact.artifact_path
