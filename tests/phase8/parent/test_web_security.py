from fastapi import FastAPI
from fastapi.testclient import TestClient
from manim_workbench_api.web_security import configure_web_security


def _app() -> FastAPI:
    app = FastAPI()
    configure_web_security(app, allowed_origins=("http://localhost:3000",), secure=False)

    @app.get("/api/v1/check")
    def check() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_security_headers_are_present_on_browser_api() -> None:
    response = TestClient(_app()).get("/api/v1/check")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"


def test_cors_allows_only_the_frozen_origin() -> None:
    client = TestClient(_app())
    allowed = client.options(
        "/api/v1/check",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    denied = client.options(
        "/api/v1/check",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in denied.headers
