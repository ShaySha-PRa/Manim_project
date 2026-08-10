from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "apps/web/src"
WEB_APP = ROOT / "apps/web"
APP_HEADER = WEB / "components/auth/app-header.tsx"
FEATURE_FLAGS = WEB / "lib/feature-flags.ts"
PLACEHOLDER = WEB / "components/feature-foundation/feature-placeholder.tsx"
LAB_PAGE = WEB / "app/lab/page.tsx"
STUDIO_PAGE = WEB / "app/studio/page.tsx"
SESSION_HOOK = WEB / "hooks/workbench/use-workbench-session.ts"
NODE_HARNESS = Path(__file__).with_name("web-runtime-harness.cjs")
NEXT_BIN = ROOT / "node_modules/next/dist/bin/next"
NEXT_ENV = WEB_APP / "next-env.d.ts"


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href is not None:
            self.hrefs.append(href)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _flag_results(values: list[str | None]) -> list[bool]:
    expressions = ["undefined" if value is None else json.dumps(value) for value in values]
    source_path = json.dumps(str(FEATURE_FLAGS))
    script = f"""
const fs = require("fs");
const ts = require("typescript");
const source = fs.readFileSync({source_path}, "utf8");
const compiled = ts.transpileModule(source, {{
  compilerOptions: {{ module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }}
}});
const module = {{ exports: {{}} }};
new Function("module", "exports", compiled.outputText)(module, module.exports);
const values = [{", ".join(expressions)}];
const results = values.map((value) => module.exports.isFeatureFlagEnabled(value));
process.stdout.write(JSON.stringify(results));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _runtime_results(command: str) -> dict[str, object]:
    completed = subprocess.run(
        ["node", str(NODE_HARNESS), command],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _http_response(url: str) -> tuple[int, str]:
    try:
        with urlopen(url, timeout=3) as response:  # noqa: S310 - localhost test server only
            return response.status, response.read().decode("utf-8")
    except HTTPError as error:
        return error.code, error.read().decode("utf-8")


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextmanager
def _next_server(lab_flag: str | None, studio_flag: str | None) -> Iterator[str]:
    port = _unused_local_port()
    environment = os.environ.copy()
    for name, value in (
        ("NEXT_PUBLIC_EXPERIMENT_LAB_ENABLED", lab_flag),
        ("NEXT_PUBLIC_STUDIO_ENABLED", studio_flag),
    ):
        if value is None:
            environment.pop(name, None)
        else:
            environment[name] = value
    environment["NEXT_TELEMETRY_DISABLED"] = "1"
    original_next_env = NEXT_ENV.read_bytes()
    process = subprocess.Popen(
        ["node", str(NEXT_BIN), "dev", "--hostname", "127.0.0.1", "--port", str(port)],
        cwd=WEB_APP,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    base_url = f"http://127.0.0.1:{port}"

    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout is not None else ""
                raise AssertionError(f"Next server exited before ready:\n{output}")
            try:
                status, _ = _http_response(f"{base_url}/login")
                if status == 200:
                    break
            except URLError:
                pass
            time.sleep(0.05)
        else:
            raise AssertionError("Next server did not become ready within 20 seconds")
        yield base_url
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
        if NEXT_ENV.read_bytes() != original_next_env:
            NEXT_ENV.write_bytes(original_next_env)


def test_feature_flag_parser_requires_exact_lowercase_true() -> None:
    values = [None, "", "false", "TRUE", "True", "1", " true", "true ", "true"]

    assert _flag_results(values) == [False, False, False, False, False, False, False, False, True]


@pytest.mark.parametrize(
    ("lab_flag", "studio_flag", "expected_feature_links"),
    [
        pytest.param(None, None, set(), id="default-off"),
        pytest.param("true", "false", {"/lab"}, id="lab-only"),
        pytest.param("false", "true", {"/studio"}, id="studio-only"),
        pytest.param("true", "true", {"/lab", "/studio"}, id="both-on"),
    ],
)
def test_next_server_exposes_navigation_and_routes_independently(
    lab_flag: str | None,
    studio_flag: str | None,
    expected_feature_links: set[str],
) -> None:
    with _next_server(lab_flag, studio_flag) as base_url:
        login_status, login_html = _http_response(f"{base_url}/login")
        lab_status, _ = _http_response(f"{base_url}/lab")
        studio_status, _ = _http_response(f"{base_url}/studio")

    parser = _LinkParser()
    parser.feed(login_html)
    actual_feature_links = {href for href in parser.hrefs if href in {"/lab", "/studio"}}

    assert login_status == 200
    assert actual_feature_links == expected_feature_links
    assert lab_status == (200 if "/lab" in expected_feature_links else 404)
    assert studio_status == (200 if "/studio" in expected_feature_links else 404)


def test_protected_placeholders_execute_loading_error_and_ready_rendering() -> None:
    results = _runtime_results("placeholder")

    loading = str(results["loading"])
    error = str(results["error"])
    lab_ready = str(results["labReady"])
    studio_ready = str(results["studioReady"])

    assert 'aria-busy="true"' in loading
    assert "正在恢复安全会话" in loading
    assert "科学实验室" not in loading
    assert 'role="alert"' in error
    assert "测试会话错误" in error
    assert "重试" in error
    assert 'id="main-content"' in lab_ready
    assert "科学实验室" in lab_ready
    assert "科学运行时、求解器、实时交互或实时渲染未启用" in lab_ready
    assert "正在恢复安全会话" not in lab_ready
    assert "Studio" in studio_ready
    assert "实验到讲解叙事的工作流或 Manim 视频生成未启用" in studio_ready


def test_session_hook_executes_ready_error_retry_and_redirect_decisions() -> None:
    results = _runtime_results("session")

    assert results["ready"] == {
        "states": ["loading", "ready"],
        "error": None,
        "redirects": [],
    }
    assert results["errorThenRetry"] == {
        "states": ["loading", "error", "ready"],
        "error": None,
        "redirects": [],
    }
    assert results["unauthorized"] == {
        "states": ["loading", "loading"],
        "error": None,
        "redirects": ["/login"],
    }
    assert results["mustChangePassword"] == {
        "states": ["loading", "loading"],
        "error": None,
        "redirects": ["/change-password"],
    }


def test_disabled_routes_call_server_not_found_before_mounting_protected_content() -> None:
    for page, flag_name, placeholder_name in (
        (LAB_PAGE, "NEXT_PUBLIC_EXPERIMENT_LAB_ENABLED", "LabPlaceholder"),
        (STUDIO_PAGE, "NEXT_PUBLIC_STUDIO_ENABLED", "StudioPlaceholder"),
    ):
        source = _read(page)

        assert 'import { notFound } from "next/navigation";' in source
        assert f"process.env.{flag_name}" in source
        assert "notFound();" in source
        assert source.index("notFound();") < source.index(f"return <{placeholder_name}")
        assert '"use client"' not in source


def test_placeholders_truthfully_describe_milestone_one_scope() -> None:
    source = _read(PLACEHOLDER)

    assert "科学运行时、求解器、实时交互或实时渲染未启用" in source
    assert "实验到讲解叙事的工作流或 Manim 视频生成未启用" in source
    assert "WebSocket" not in source
    assert "DeepSeek" not in source
    assert "PDE" not in source
    assert "GPU" not in source


def test_new_web_sources_do_not_add_execution_or_client_credential_paths() -> None:
    source = "\n".join(
        _read(path) for path in (APP_HEADER, FEATURE_FLAGS, PLACEHOLDER, LAB_PAGE, STUDIO_PAGE)
    )

    for forbidden in (
        "localStorage",
        "sessionStorage",
        "Authorization",
        "owner_id",
        "workbenchApi",
        "WebSocket",
        "EventSource",
        "fetch(",
        "/api/",
        "execute(",
        "render(",
    ):
        assert forbidden not in source


def test_workbench_sources_are_unchanged_from_task_three_base() -> None:
    paths = [
        *sorted((WEB / "app/workbench").rglob("*.ts*")),
        *sorted((WEB / "components/workbench").rglob("*.ts*")),
        *sorted((WEB / "hooks/workbench").rglob("*.ts*")),
    ]

    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        completed = subprocess.run(
            ["git", "show", f"2828bdc:{relative}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        assert completed.stdout.decode() == _read(path), relative
