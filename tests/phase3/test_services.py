import json
import subprocess
import sys

from fastapi.testclient import TestClient
from manim_workbench_api.main import app


def test_api_health_contract() -> None:
    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "api",
        "contract_schema_version": "1.12",
    }


def test_runner_has_safe_phase3_smoke_entrypoint() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "manim_workbench_runner"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "status": "idle",
        "service": "runner",
        "contract_schema_version": "1.12",
        "docker_access": False,
    }
