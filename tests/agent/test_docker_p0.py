import subprocess
from pathlib import Path

import pytest
from manim_workbench_api.agent.p0_acceptance import docker_image_ready, evaluate_gold
from manim_workbench_runner.rendering.models import MANIM_IMAGE


def _docker_ready() -> bool:
    probe = subprocess.run(
        ["docker", "image", "inspect", MANIM_IMAGE],
        check=False,
        capture_output=True,
        text=True,
    )
    return probe.returncode == 0


@pytest.mark.skipif(not _docker_ready(), reason="Docker Manim image is not present")
def test_p0_gold_meets_first_render_and_science_rates(tmp_path: Path) -> None:
    assert docker_image_ready()
    report = evaluate_gold(work_root=tmp_path, render=True)
    assert report.meets_p0_gates, report.as_dict()
    assert report.first_render_rate is not None
    assert report.first_render_rate >= report.first_render_min
    assert report.final_success_rate >= report.final_success_min
    assert report.science_rate >= report.science_min
