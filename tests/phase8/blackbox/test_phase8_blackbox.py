from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from manim_workbench_api.auth.dependencies import get_auth_engine, get_auth_settings
from manim_workbench_api.auth.models import AuthSettings
from manim_workbench_api.auth.router import router as auth_router
from manim_workbench_api.auth.service import AuthService
from manim_workbench_api.code_generation.dependencies import (
    get_code_generation_provider,
    get_code_generation_renderer,
)
from manim_workbench_api.code_generation.models import CandidateRenderResult
from manim_workbench_api.content_plans.dependencies import get_content_plan_provider
from manim_workbench_api.content_plans.errors import ContentPlanError, ContentPlanErrorCode
from manim_workbench_api.content_plans.models import ProviderResult, ProviderUsage
from manim_workbench_api.delivery.dependencies import get_delivery_service
from manim_workbench_api.delivery.router import router as delivery_router
from manim_workbench_api.delivery.service import DeliveryService
from manim_workbench_api.jobs.dependencies import get_job_signal_publisher
from manim_workbench_api.projects.dependencies import get_project_engine
from manim_workbench_api.projects.router import router as projects_router
from manim_workbench_api.workspace.dependencies import get_workspace_engine
from manim_workbench_api.workspace.router import router as workspace_router
from sqlalchemy import Engine, create_engine, text

ROOT = Path(__file__).resolve().parents[3]
ORIGIN = "http://testserver"
INITIAL_PASSWORD = "initial-correct-horse-battery"
READY_PASSWORD = "ready-correct-horse-battery"
OTHER_PASSWORD = "other-correct-horse-battery"


class StaticContentProvider:
    def __init__(self, content: str | Exception) -> None:
        self.content = content
        self.calls = 0

    def generate(self, messages: tuple[object, ...]) -> ProviderResult:
        assert len(messages) == 2
        self.calls += 1
        if isinstance(self.content, Exception):
            raise self.content
        return ProviderResult(
            content=self.content,
            finish_reason="stop",
            request_id="offline-content-provider",
            model="offline-fake",
            usage=ProviderUsage(prompt_tokens=1, completion_tokens=1),
        )


class StaticCodeProvider(StaticContentProvider):
    pass


class AcceptingRenderer:
    def __init__(self) -> None:
        self.calls = 0

    def render(self, source_code: str, scene_class: str) -> CandidateRenderResult:
        del source_code, scene_class
        self.calls += 1
        return CandidateRenderResult(succeeded=True)


class NullPublisher:
    def publish(self, job_id: UUID) -> None:
        del job_id


@dataclass
class BlackboxHarness:
    app: FastAPI
    engine: Engine
    artifact_root: Path
    content_provider: StaticContentProvider
    code_provider: StaticCodeProvider
    renderer: AcceptingRenderer


def _ready_content_plan() -> str:
    return json.dumps(
        {
            "outcome": "ready",
            "plan": {
                "schema_version": "1.1",
                "title": "一次函数",
                "audience": "high_school",
                "language": "zh-CN",
                "target_duration_seconds": 60,
                "derivation_style": "visual_intuition",
                "explicit_assumptions": ["学习者理解坐标系。"],
                "ambiguities": [],
                "scenes": [
                    {
                        "scene_number": 1,
                        "teaching_goal": "理解斜率。",
                        "formula_steps": [{"expression": "y=kx", "explanation": "斜率控制倾斜。"}],
                        "visual_intent": "在坐标轴上绘制定义域 x∈[-3,3] 的函数图像。",
                        "narration_placeholder": "比较斜率变化时直线递增的关键行为。",
                    }
                ],
            },
            "clarifications": [],
            "limitations": [],
        },
        ensure_ascii=False,
    )


def _safe_generated_scene() -> str:
    return json.dumps(
        {
            "scene_class": "GeneratedScene",
            "code": (
                "from manim import Scene, Text\n\n"
                "class GeneratedScene(Scene):\n"
                "    def construct(self):\n"
                "        title = Text('Linear function')\n"
                "        self.add(title)\n"
                "        self.wait(0.1)\n"
            ),
            "assumptions": ["Use a readable title."],
        }
    )


def _migrated_engine(tmp_path: Path) -> Engine:
    tmp_path.mkdir(parents=True, exist_ok=True)
    database_path = tmp_path / "phase8-blackbox.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    return create_engine(f"sqlite:///{database_path}")


def _build_harness(
    tmp_path: Path,
    *,
    content_result: str | Exception | None = None,
    code_result: str | Exception | None = None,
    engine: Engine | None = None,
    artifact_root: Path | None = None,
) -> BlackboxHarness:
    shared_engine = engine or _migrated_engine(tmp_path)
    root = artifact_root or tmp_path / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    content_provider = StaticContentProvider(content_result or _ready_content_plan())
    code_provider = StaticCodeProvider(code_result or _safe_generated_scene())
    renderer = AcceptingRenderer()
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(delivery_router, prefix="/api/v1")
    app.include_router(workspace_router, prefix="/api/v1")
    settings = AuthSettings(allowed_origins=frozenset({ORIGIN}), cookie_secure=False)
    app.dependency_overrides[get_auth_engine] = lambda: shared_engine
    app.dependency_overrides[get_auth_settings] = lambda: settings
    app.dependency_overrides[get_project_engine] = lambda: shared_engine
    app.dependency_overrides[get_workspace_engine] = lambda: shared_engine
    app.dependency_overrides[get_delivery_service] = lambda: DeliveryService(shared_engine, root)
    app.dependency_overrides[get_content_plan_provider] = lambda: content_provider
    app.dependency_overrides[get_code_generation_provider] = lambda: code_provider
    app.dependency_overrides[get_code_generation_renderer] = lambda: renderer
    app.dependency_overrides[get_job_signal_publisher] = lambda: NullPublisher()
    return BlackboxHarness(app, shared_engine, root, content_provider, code_provider, renderer)


@pytest.fixture
def harness(tmp_path: Path) -> BlackboxHarness:
    result = _build_harness(tmp_path)
    users = AuthService(result.engine)
    users.create_user("teacher-a@example.test", INITIAL_PASSWORD)
    users.create_user("teacher-b@example.test", OTHER_PASSWORD)
    return result


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, client=("127.0.0.1", 4567))


def _login(client: TestClient, email: str, password: str) -> Any:
    return client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": email, "password": password},
    )


def _ready_client(
    app: FastAPI, email: str, password: str, new_password: str
) -> tuple[TestClient, str]:
    client = _client(app)
    login = _login(client, email, password)
    assert login.status_code == 200, login.text
    changed = client.post(
        "/api/v1/auth/change-password",
        headers={"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]},
        json={"current_password": password, "new_password": new_password},
    )
    assert changed.status_code == 200, changed.text
    return client, str(changed.json()["csrf_token"])


def _mutation_headers(csrf_token: str) -> dict[str, str]:
    return {"Origin": ORIGIN, "X-CSRF-Token": csrf_token}


def _create_complete_workflow(
    harness: BlackboxHarness, client: TestClient, csrf_token: str
) -> dict[str, str]:
    project = client.post(
        "/api/v1/projects", json={"title": "黑盒项目"}, headers=_mutation_headers(csrf_token)
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    prompt = client.post(
        f"/api/v1/projects/{project_id}/prompt-versions",
        json={"prompt": "解释一次函数斜率。"},
        headers=_mutation_headers(csrf_token),
    )
    assert prompt.status_code == 201, prompt.text
    prompt_id = prompt.json()["id"]
    plan = client.post(
        f"/api/v1/workspace/projects/{project_id}/content-plans/generate",
        json={
            "prompt_version_id": prompt_id,
            "audience": "high_school",
            "target_duration_seconds": 60,
            "derivation_style": "visual_intuition",
        },
        headers=_mutation_headers(csrf_token),
    )
    assert plan.status_code == 200, plan.text
    plan_id = plan.json()["content_plan_version"]["id"]
    code = client.post(
        f"/api/v1/workspace/projects/{project_id}/code-generations",
        json={
            "prompt_version_id": prompt_id,
            "content_plan_version_id": plan_id,
            "category": "function_visualization",
        },
        headers=_mutation_headers(csrf_token),
    )
    assert code.status_code == 200, code.text
    code_id = code.json()["code_version"]["id"]
    job = client.post(
        f"/api/v1/workspace/projects/{project_id}/render-jobs",
        json={
            "code_version_id": code_id,
            "profile": "preview",
            "idempotency_key": "phase8-blackbox-preview-001",
        },
        headers=_mutation_headers(csrf_token),
    )
    assert job.status_code == 201, job.text
    return {
        "project_id": str(project_id),
        "prompt_id": str(prompt_id),
        "plan_id": str(plan_id),
        "code_id": str(code_id),
        "job_id": str(job.json()["id"]),
    }


def _insert_artifact(harness: BlackboxHarness, ids: dict[str, str]) -> str:
    artifact_id = uuid4()
    content = b"offline-video-bytes"
    relative_path = "safe/preview.mp4"
    artifact_path = harness.artifact_root / relative_path
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(content)
    with harness.engine.begin() as connection:
        owner_id = connection.execute(
            text("SELECT owner_id FROM projects WHERE id = :id"), {"id": ids["project_id"]}
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO artifacts (id, project_id, owner_id, render_job_id, kind, "
                "relative_path, sha256, byte_size, created_at) VALUES "
                "(:id, :project_id, :owner_id, :render_job_id, 'video', :relative_path, "
                ":sha256, :byte_size, :created_at)"
            ),
            {
                "id": str(artifact_id),
                "project_id": ids["project_id"],
                "owner_id": owner_id,
                "render_job_id": ids["job_id"],
                "relative_path": relative_path,
                "sha256": sha256(content).hexdigest(),
                "byte_size": len(content),
                "created_at": "2026-08-05T00:00:00+00:00",
            },
        )
    return str(artifact_id)


def _terminalize_job(harness: BlackboxHarness, job_id: str) -> None:
    with harness.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE render_jobs SET status = 'succeeded', state_version = state_version + 1, "
                "finished_at = :finished_at WHERE id = :id"
            ),
            {"id": job_id, "finished_at": "2026-08-05T00:01:00+00:00"},
        )


def test_two_user_cross_access_matrix_hides_existence_for_every_browser_resource(
    harness: BlackboxHarness,
) -> None:
    owner, csrf_a = _ready_client(
        harness.app, "teacher-a@example.test", INITIAL_PASSWORD, READY_PASSWORD
    )
    other, csrf_b = _ready_client(
        harness.app, "teacher-b@example.test", OTHER_PASSWORD, "second-ready-password"
    )
    ids = _create_complete_workflow(harness, owner, csrf_a)
    artifact_id = _insert_artifact(harness, ids)
    _terminalize_job(harness, ids["job_id"])

    source = owner.get(f"/api/v1/workspace/code-versions/{ids['code_id']}/source")
    assert source.status_code == 200
    assert source.headers["content-type"].startswith("text/plain")
    assert source.headers["x-content-type-options"] == "nosniff"
    assert owner.post(f"/api/v1/workspace/code-versions/{ids['code_id']}/source").status_code == 405

    cases = (
        ("project", f"/api/v1/projects/{ids['project_id']}", None),
        ("prompt_version", f"/api/v1/projects/{ids['project_id']}/prompt-versions", None),
        (
            "content_plan_version",
            f"/api/v1/projects/{ids['project_id']}/content-plan-versions",
            None,
        ),
        ("code_version", f"/api/v1/workspace/code-versions/{ids['code_id']}/source", None),
        ("render_job", f"/api/v1/workspace/render-jobs/{ids['job_id']}", None),
        ("sse", f"/api/v1/render-jobs/{ids['job_id']}/events", None),
        ("artifact", f"/api/v1/artifacts/{artifact_id}", None),
    )
    for resource, url, params in cases:
        denied = other.get(url, params=params)
        unknown_url = url.replace(ids["project_id"], str(uuid4()))
        unknown_url = unknown_url.replace(ids["job_id"], str(uuid4()))
        unknown_url = unknown_url.replace(ids["code_id"], str(uuid4()))
        unknown = other.get(unknown_url.replace(artifact_id, str(uuid4())), params=params)
        assert denied.status_code == unknown.status_code == 404, resource
        assert denied.json() == unknown.json(), resource

    unauthorized_mutation = other.post(
        f"/api/v1/workspace/projects/{ids['project_id']}/render-jobs",
        json={
            "code_version_id": ids["code_id"],
            "profile": "final",
            "idempotency_key": "phase8-cross-owner-final-01",
        },
        headers=_mutation_headers(csrf_b),
    )
    assert unauthorized_mutation.status_code == 404
    assert unauthorized_mutation.json()["error"]["code"] == "project_not_found"


def test_authentication_attack_matrix_rejects_fixation_csrf_enumeration_and_replay(
    harness: BlackboxHarness,
) -> None:
    attacker = _client(harness.app)
    attacker.cookies.set(
        "manim_workbench_session",
        "attacker-fixed-value",
        domain="testserver.local",
        path="/",
    )
    fixed = attacker.get("/api/v1/auth/session")
    assert fixed.status_code == 401

    login = _login(attacker, "teacher-a@example.test", INITIAL_PASSWORD)
    assert login.status_code == 200
    issued_token = attacker.cookies.get(
        "manim_workbench_session", domain="testserver.local", path="/"
    )
    assert issued_token and issued_token != "attacker-fixed-value"
    must_change = attacker.post(
        "/api/v1/projects",
        json={"title": "must not create"},
        headers={"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]},
    )
    assert must_change.status_code == 403

    changed = attacker.post(
        "/api/v1/auth/change-password",
        headers={"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]},
        json={"current_password": INITIAL_PASSWORD, "new_password": READY_PASSWORD},
    )
    assert changed.status_code == 200
    stale = _client(harness.app)
    stale.cookies.set("manim_workbench_session", issued_token)
    assert stale.get("/api/v1/auth/session").status_code == 401

    csrf_missing = attacker.post("/api/v1/auth/logout", headers={"Origin": ORIGIN})
    csrf_cross_origin = attacker.post(
        "/api/v1/auth/logout",
        headers={
            "Origin": "https://attacker.invalid",
            "X-CSRF-Token": changed.json()["csrf_token"],
        },
    )
    assert csrf_missing.status_code == csrf_cross_origin.status_code == 403
    assert csrf_missing.json() == csrf_cross_origin.json()

    unknown = _login(_client(harness.app), "unknown@example.test", INITIAL_PASSWORD)
    wrong = _login(_client(harness.app), "teacher-b@example.test", "wrong-correct-horse-battery")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    limited = _client(harness.app)
    for _ in range(4):
        response = _login(limited, "teacher-b@example.test", "wrong-correct-horse-battery")
        assert response.status_code == 401
    assert _login(limited, "teacher-b@example.test", OTHER_PASSWORD).status_code == 429


def test_sse_reconnect_is_durable_terminal_is_unique_and_api_restart_preserves_session(
    harness: BlackboxHarness, tmp_path: Path
) -> None:
    owner, csrf_a = _ready_client(
        harness.app, "teacher-a@example.test", INITIAL_PASSWORD, READY_PASSWORD
    )
    ids = _create_complete_workflow(harness, owner, csrf_a)
    _terminalize_job(harness, ids["job_id"])
    initial = owner.get(f"/api/v1/render-jobs/{ids['job_id']}/events")
    assert initial.status_code == 200
    assert initial.text.count("event: render_job") == 2
    assert initial.text.count('"status":"succeeded"') == 1
    replay = owner.get(
        f"/api/v1/render-jobs/{ids['job_id']}/events", headers={"Last-Event-ID": "1"}
    )
    assert replay.status_code == 200
    assert replay.text.count("event: render_job") == 1
    assert '"status":"succeeded"' in replay.text

    token = owner.cookies.get("manim_workbench_session")
    restarted = _build_harness(
        tmp_path,
        engine=harness.engine,
        artifact_root=harness.artifact_root,
    )
    after_restart = _client(restarted.app)
    after_restart.cookies.set("manim_workbench_session", token)
    assert after_restart.get("/api/v1/auth/session").status_code == 200
    resumed = after_restart.get(
        f"/api/v1/render-jobs/{ids['job_id']}/events", headers={"Last-Event-ID": "1"}
    )
    assert resumed.status_code == 200
    assert resumed.text.count("event: render_job") == 1


@pytest.mark.parametrize(
    "relative_path, create_file, mutate_after_insert",
    (
        ("../outside.mp4", False, False),
        ("/absolute/outside.mp4", False, False),
        (r"..\\outside.mp4", False, False),
        (r"C:\\outside.mp4", False, False),
        ("safe/hash-mismatch.mp4", True, True),
        ("safe/size-mismatch.mp4", True, True),
    ),
)
def test_artifact_attack_corpus_fails_closed(
    harness: BlackboxHarness,
    relative_path: str,
    create_file: bool,
    mutate_after_insert: bool,
) -> None:
    owner, csrf_a = _ready_client(
        harness.app, "teacher-a@example.test", INITIAL_PASSWORD, READY_PASSWORD
    )
    ids = _create_complete_workflow(harness, owner, csrf_a)
    artifact_id = uuid4()
    content = b"expected-artifact"
    if create_file:
        path = harness.artifact_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    with harness.engine.begin() as connection:
        owner_id = connection.execute(
            text("SELECT owner_id FROM projects WHERE id = :id"), {"id": ids["project_id"]}
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO artifacts (id, project_id, owner_id, render_job_id, kind, "
                "relative_path, sha256, byte_size, created_at) VALUES "
                "(:id, :project_id, :owner_id, :job_id, 'video', :relative_path, :sha256, "
                ":byte_size, :created_at)"
            ),
            {
                "id": str(artifact_id),
                "project_id": ids["project_id"],
                "owner_id": owner_id,
                "job_id": ids["job_id"],
                "relative_path": relative_path,
                "sha256": sha256(content).hexdigest(),
                "byte_size": len(content) + (1 if "size-mismatch" in relative_path else 0),
                "created_at": "2026-08-05T00:00:00+00:00",
            },
        )
    if mutate_after_insert and "hash-mismatch" in relative_path:
        (harness.artifact_root / relative_path).write_bytes(b"tampered")
    rejected = owner.get(f"/api/v1/artifacts/{artifact_id}")
    assert rejected.status_code == 404
    assert rejected.json() == {
        "error": {"code": "artifact_not_found", "message": "Artifact was not found."}
    }


def test_artifact_symlink_and_content_type_confusion_are_blocked_or_fixed(
    harness: BlackboxHarness,
) -> None:
    owner, csrf_a = _ready_client(
        harness.app, "teacher-a@example.test", INITIAL_PASSWORD, READY_PASSWORD
    )
    ids = _create_complete_workflow(harness, owner, csrf_a)
    outside = harness.artifact_root.parent / "outside.mp4"
    outside.write_bytes(b"outside")
    link = harness.artifact_root / "safe" / "linked.mp4"
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink support is unavailable on this filesystem")
    symlink_id = uuid4()
    html_id = uuid4()
    html_content = b"not-html"
    html_path = harness.artifact_root / "safe" / "movie.html"
    html_path.write_bytes(html_content)
    with harness.engine.begin() as connection:
        owner_id = connection.execute(
            text("SELECT owner_id FROM projects WHERE id = :id"), {"id": ids["project_id"]}
        ).scalar_one()
        for artifact_id, relative_path, content in (
            (symlink_id, "safe/linked.mp4", b"outside"),
            (html_id, "safe/movie.html", html_content),
        ):
            connection.execute(
                text(
                    "INSERT INTO artifacts (id, project_id, owner_id, render_job_id, kind, "
                    "relative_path, sha256, byte_size, created_at) VALUES "
                    "(:id, :project_id, :owner_id, :job_id, 'video', :relative_path, :sha256, "
                    ":byte_size, :created_at)"
                ),
                {
                    "id": str(artifact_id),
                    "project_id": ids["project_id"],
                    "owner_id": owner_id,
                    "job_id": ids["job_id"],
                    "relative_path": relative_path,
                    "sha256": sha256(content).hexdigest(),
                    "byte_size": len(content),
                    "created_at": "2026-08-05T00:00:00+00:00",
                },
            )
    assert owner.get(f"/api/v1/artifacts/{symlink_id}").status_code == 404
    safe_mime = owner.get(f"/api/v1/artifacts/{html_id}")
    assert safe_mime.status_code == 200
    assert safe_mime.headers["content-type"].startswith("video/mp4")
    assert safe_mime.headers["x-content-type-options"] == "nosniff"


def test_fake_phase5_to_phase7_chain_has_success_and_stage_mapped_failures(tmp_path: Path) -> None:
    success = _build_harness(tmp_path)
    users = AuthService(success.engine)
    users.create_user("teacher-a@example.test", INITIAL_PASSWORD)
    owner, csrf_a = _ready_client(
        success.app, "teacher-a@example.test", INITIAL_PASSWORD, READY_PASSWORD
    )
    ids = _create_complete_workflow(success, owner, csrf_a)
    assert success.content_provider.calls == 1
    assert success.code_provider.calls == 1
    assert success.renderer.calls == 1
    assert owner.get(f"/api/v1/workspace/render-jobs/{ids['job_id']}").status_code == 200

    unavailable = _build_harness(
        tmp_path / "unavailable",
        content_result=ContentPlanError(ContentPlanErrorCode.PROVIDER_UNAVAILABLE, "hidden"),
    )
    AuthService(unavailable.engine).create_user("teacher-a@example.test", INITIAL_PASSWORD)
    client, csrf = _ready_client(
        unavailable.app, "teacher-a@example.test", INITIAL_PASSWORD, READY_PASSWORD
    )
    project = client.post(
        "/api/v1/projects", json={"title": "错误映射"}, headers=_mutation_headers(csrf)
    )
    prompt = client.post(
        f"/api/v1/projects/{project.json()['id']}/prompt-versions",
        json={"prompt": "解释一次函数斜率。"},
        headers=_mutation_headers(csrf),
    )
    content_failure = client.post(
        f"/api/v1/workspace/projects/{project.json()['id']}/content-plans/generate",
        json={"prompt_version_id": prompt.json()["id"]},
        headers=_mutation_headers(csrf),
    )
    assert content_failure.status_code == 503
    assert content_failure.json()["error"]["stage"] == "content_plan"
    assert "hidden" not in content_failure.text

    unsafe = _build_harness(
        tmp_path / "unsafe",
        code_result=json.dumps(
            {
                "scene_class": "GeneratedScene",
                "code": (
                    "from manim import Scene\nclass GeneratedScene(Scene):\n"
                    "    def construct(self):\n        open('x')\n"
                ),
                "assumptions": [],
            }
        ),
    )
    AuthService(unsafe.engine).create_user("teacher-a@example.test", INITIAL_PASSWORD)
    unsafe_client, unsafe_csrf = _ready_client(
        unsafe.app, "teacher-a@example.test", INITIAL_PASSWORD, READY_PASSWORD
    )
    unsafe_ids = _create_complete_workflow_until_plan(unsafe, unsafe_client, unsafe_csrf)
    code_failure = unsafe_client.post(
        f"/api/v1/workspace/projects/{unsafe_ids['project_id']}/code-generations",
        json={
            "prompt_version_id": unsafe_ids["prompt_id"],
            "content_plan_version_id": unsafe_ids["plan_id"],
            "category": "function_visualization",
        },
        headers=_mutation_headers(unsafe_csrf),
    )
    assert code_failure.status_code == 422
    assert code_failure.json()["error"]["stage"] == "code_generation"
    assert unsafe.renderer.calls == 0


def _create_complete_workflow_until_plan(
    harness: BlackboxHarness, client: TestClient, csrf_token: str
) -> dict[str, str]:
    project = client.post(
        "/api/v1/projects", json={"title": "黑盒项目"}, headers=_mutation_headers(csrf_token)
    )
    assert project.status_code == 201
    project_id = project.json()["id"]
    prompt = client.post(
        f"/api/v1/projects/{project_id}/prompt-versions",
        json={"prompt": "解释一次函数斜率。"},
        headers=_mutation_headers(csrf_token),
    )
    assert prompt.status_code == 201
    plan = client.post(
        f"/api/v1/workspace/projects/{project_id}/content-plans/generate",
        json={
            "prompt_version_id": prompt.json()["id"],
            "audience": "high_school",
            "target_duration_seconds": 60,
            "derivation_style": "visual_intuition",
        },
        headers=_mutation_headers(csrf_token),
    )
    assert plan.status_code == 200
    return {
        "project_id": str(project_id),
        "prompt_id": str(prompt.json()["id"]),
        "plan_id": str(plan.json()["content_plan_version"]["id"]),
    }
