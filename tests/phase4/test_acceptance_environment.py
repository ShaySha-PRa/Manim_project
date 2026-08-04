import json
from pathlib import Path

import pytest
from manim_workbench_runner.rendering import MANIM_IMAGE_DIGEST, CommandResult

from benchmarks.phase4.run_acceptance import preserve_environment, probe_environment


class EnvironmentRunner:
    def run(self, command: list[str], *, timeout_seconds: int) -> CommandResult:
        assert command[:3] == ["docker", "run", "--rm"]
        assert timeout_seconds == 30
        payload = {
            "python_version": "3.14.3",
            "manim_version": "0.20.1",
            "pyav_version": "16.1.0",
            "ffmpeg_libraries": {"libavcodec": [62, 11, 100]},
            "latex_version": "pdfTeX 3.141592653",
            "fonts": ["Noto Sans", "Noto Serif", "Noto Sans Mono"],
        }
        return CommandResult(tuple(command), 0, json.dumps(payload), 0.1)


def test_environment_probe_adds_the_immutable_image_identity() -> None:
    result = probe_environment(EnvironmentRunner())

    assert result["manim_version"] == "0.20.1"
    assert result["pyav_version"] == "16.1.0"
    assert result["image_digest"] == MANIM_IMAGE_DIGEST


def test_preserved_environment_is_immutable_across_resume(tmp_path: Path) -> None:
    path = tmp_path / "environment.json"
    environment = probe_environment(EnvironmentRunner())

    preserve_environment(path, environment)
    preserve_environment(path, environment)
    with pytest.raises(RuntimeError, match="changed"):
        preserve_environment(path, {**environment, "pyav_version": "changed"})
