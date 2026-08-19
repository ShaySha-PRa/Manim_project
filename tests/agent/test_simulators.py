from pathlib import Path

import numpy as np
from manim_workbench_api.tools.kernels import KernelResult, allowed_ops, run_kernel
from manim_workbench_api.tools.simulators import register_simulator, unregister_simulator
from manim_workbench_runner.sandbox.compute_runtime import ComputeSandboxError, execute_tool


def test_register_simulator_is_allowlisted_until_unregistered(tmp_path: Path) -> None:
    def constant_field(params, input_text):
        del params, input_text
        return KernelResult(
            arrays={"values": np.asarray([1.0, 2.0])},
            assertions={"plugin": True},
        )

    register_simulator("constant_field", constant_field)
    try:
        assert "constant_field" in allowed_ops()
        artifact = execute_tool("constant_field", {}, output_root=tmp_path)
        assert artifact.assertions["plugin"] is True
        packed = np.load(artifact.artifact_path, allow_pickle=False)
        assert packed["values"].tolist() == [1.0, 2.0]
    finally:
        unregister_simulator("constant_field")
    assert "constant_field" not in allowed_ops()
    try:
        execute_tool("constant_field", {}, output_root=tmp_path)
    except ComputeSandboxError as error:
        assert "allowlisted" in str(error)
    else:
        raise AssertionError("unregistered simulator must fail closed")


def test_model_cannot_register_dotted_or_uppercase_ops() -> None:
    def dummy(params, input_text):
        del params, input_text
        return KernelResult(arrays={"values": np.asarray([0.0])}, assertions={})

    try:
        register_simulator("os.system", dummy)
    except ValueError as error:
        assert "invalid" in str(error)
    else:
        raise AssertionError("dotted names must be rejected")
    try:
        register_simulator("Wave2D", dummy)
    except ValueError as error:
        assert "invalid" in str(error)
    else:
        raise AssertionError("uppercase names must be rejected")
    assert "os.system" not in allowed_ops()
    run_kernel("fourier_square_wave", {"n_max": 3}, None)
