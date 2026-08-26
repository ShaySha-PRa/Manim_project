from __future__ import annotations

import subprocess
import sys
from importlib.metadata import version


def test_pinned_asgi_stack_runs_sync_dependency_and_endpoint() -> None:
    assert version("fastapi") == "0.139.2"
    assert version("starlette") == "1.3.1"
    assert version("anyio") == "4.14.2"

    probe = """
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

app = FastAPI()

def dependency() -> str:
    return "ready"

@app.get("/sync")
def sync_endpoint(value: str = Depends(dependency)) -> dict[str, str]:
    return {"value": value}

with TestClient(app) as client:
    response = client.get("/sync")
    assert response.status_code == 200, response.text
    assert response.json() == {"value": "ready"}
"""
    subprocess.run(
        [sys.executable, "-c", probe],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
