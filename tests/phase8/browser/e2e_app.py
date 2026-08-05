from __future__ import annotations

import json
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
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
from manim_workbench_api.content_plans.models import ProviderResult, ProviderUsage
from manim_workbench_api.delivery.dependencies import get_delivery_service
from manim_workbench_api.delivery.router import router as delivery_router
from manim_workbench_api.delivery.service import DeliveryService
from manim_workbench_api.jobs.dependencies import get_job_signal_publisher
from manim_workbench_api.projects.dependencies import get_project_engine
from manim_workbench_api.projects.router import router as projects_router
from manim_workbench_api.web_security import configure_web_security
from manim_workbench_api.workspace.dependencies import get_workspace_engine
from manim_workbench_api.workspace.router import router as workspace_router
from sqlalchemy import Engine, create_engine, text

ROOT = Path(__file__).resolve().parents[3]
WEB_ORIGIN = "http://localhost:13000"
RUNTIME_ROOT = ROOT / "runtime" / "phase8-browser-gate"
DATABASE_PATH = RUNTIME_ROOT / "phase8-browser.db"
ARTIFACT_ROOT = RUNTIME_ROOT / "artifacts"
FIXTURE_ROOT = (
    ROOT
    / "runtime"
    / "phase4-smoke"
    / "6559249cd89c78479eb427b8996e9749d6d19b0fada2cd188a8589e3f37267d7"
)
INITIAL_PASSWORD = "phase8-initial-password"


class StaticProvider:
    def __init__(self, content: str) -> None:
        self.content = content

    def generate(self, messages: tuple[object, ...]) -> ProviderResult:
        if len(messages) != 2:
            raise AssertionError("offline provider requires system and user messages")
        return ProviderResult(
            content=self.content,
            finish_reason="stop",
            request_id="phase8-browser-offline",
            model="offline-gate",
            usage=ProviderUsage(prompt_tokens=1, completion_tokens=1),
        )


class AcceptingRenderer:
    def render(self, source_code: str, scene_class: str) -> CandidateRenderResult:
        if not source_code or not scene_class:
            raise AssertionError("generated scene must be non-empty")
        return CandidateRenderResult(succeeded=True)


class OfflineArtifactPublisher:
    """Complete jobs asynchronously so a real browser observes queued and SSE replay."""

    def __init__(self, engine: Engine, artifact_root: Path) -> None:
        self.engine = engine
        self.artifact_root = artifact_root

    def publish(self, job_id: UUID) -> None:
        threading.Thread(target=self._complete, args=(job_id,), daemon=True).start()

    def _complete(self, job_id: UUID) -> None:
        try:
            time.sleep(2.0)
            with self.engine.connect() as connection:
                row = connection.execute(
                    text(
                        "SELECT project_id, owner_id FROM render_jobs WHERE id = :id"
                    ),
                    {"id": str(job_id)},
                ).mappings().one()
            job_root = self.artifact_root / str(job_id)
            job_root.mkdir(parents=True, exist_ok=True)
            sources = {
                # Playwright Chromium omits H.264; use a project-local VP9-in-MP4
                # delivery fixture while retaining a real Manim thumbnail/log/metadata set.
                "video": ROOT / "runtime" / "phase8-media" / "video-vp9.mp4",
                "thumbnail": FIXTURE_ROOT / "thumbnail.jpg",
                "render_log": FIXTURE_ROOT / "render.log",
                "metadata": FIXTURE_ROOT / "metadata.json",
            }
            now = datetime.now(timezone.utc).isoformat()
            with self.engine.begin() as connection:
                for kind, source in sources.items():
                    if not source.is_file():
                        raise FileNotFoundError(source)
                    destination = job_root / source.name
                    shutil.copyfile(source, destination)
                    payload = destination.read_bytes()
                    connection.execute(
                        text(
                            "INSERT INTO artifacts "
                            "(id, project_id, owner_id, render_job_id, kind, relative_path, "
                            "sha256, byte_size, created_at) VALUES "
                            "(:id, :project_id, :owner_id, :job_id, :kind, :relative_path, "
                            ":sha256, :byte_size, :created_at)"
                        ),
                        {
                            "id": str(uuid4()),
                            "project_id": row["project_id"],
                            "owner_id": row["owner_id"],
                            "job_id": str(job_id),
                            "kind": kind,
                            "relative_path": f"{job_id}/{source.name}",
                            "sha256": sha256(payload).hexdigest(),
                            "byte_size": len(payload),
                            "created_at": now,
                        },
                    )
                connection.execute(
                    text(
                        "UPDATE render_jobs SET status = 'succeeded', attempt_count = 1, "
                        "state_version = state_version + 1, started_at = :now, "
                        "finished_at = :now WHERE id = :id AND status = 'queued'"
                    ),
                    {"id": str(job_id), "now": now},
                )
        except Exception as error:  # pragma: no cover - surfaced by browser assertions
            (RUNTIME_ROOT / "publisher-error.log").write_text(
                f"{type(error).__name__}: {error}", encoding="utf-8"
            )


def _content_plan() -> str:
    return json.dumps(
        {
            "outcome": "ready",
            "plan": {
                "schema_version": "1.1",
                "title": "一次函数斜率",
                "audience": "high_school",
                "language": "zh-CN",
                "target_duration_seconds": 60,
                "derivation_style": "visual_intuition",
                "explicit_assumptions": ["学习者理解坐标系。"],
                "ambiguities": [],
                "scenes": [
                    {
                        "scene_number": 1,
                        "teaching_goal": "理解斜率如何控制直线。",
                        "formula_steps": [
                            {"expression": "y=kx", "explanation": "k 控制倾斜程度。"}
                        ],
                        "visual_intent": (
                            "在坐标系中动态绘制定义域 x∈[-3,3] 的不同斜率一次函数。"
                        ),
                        "narration_placeholder": "比较不同 k 值下图像的变化。",
                    }
                ],
            },
            "clarifications": [],
            "limitations": [],
        },
        ensure_ascii=False,
    )


def _generated_scene() -> str:
    return json.dumps(
        {
            "scene_class": "GeneratedScene",
            "code": (
                "from manim import Scene\n\n"
                "class GeneratedScene(Scene):\n"
                "    def construct(self):\n"
                "        self.wait(0.1)\n"
            ),
            "assumptions": ["Use deterministic axes."],
        }
    )


def _prepare_engine() -> Engine:
    if os.environ.get("PHASE8_BROWSER_RESET") == "1" and RUNTIME_ROOT.exists():
        shutil.rmtree(RUNTIME_ROOT)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{DATABASE_PATH}")
    command.upgrade(config, "head")
    engine = create_engine(
        f"sqlite:///{DATABASE_PATH}", connect_args={"check_same_thread": False}
    )
    with engine.connect() as connection:
        has_users = connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one() > 0
    if not has_users:
        users = AuthService(engine)
        for suffix in ("a", "b"):
            users.create_user(f"teacher-{suffix}@example.test", INITIAL_PASSWORD)
    return engine


engine = _prepare_engine()
settings = AuthSettings(allowed_origins=frozenset({WEB_ORIGIN}), cookie_secure=False)
content_provider = StaticProvider(_content_plan())
code_provider = StaticProvider(_generated_scene())
publisher = OfflineArtifactPublisher(engine, ARTIFACT_ROOT)
observed_last_event_ids: list[int] = []

app = FastAPI(title="Phase 8 isolated browser gate")
configure_web_security(app, allowed_origins=(WEB_ORIGIN,), secure=False)


@app.middleware("http")
async def observe_sse_reconnect(request: Request, call_next):  # type: ignore[no-untyped-def]
    if request.url.path.endswith("/events"):
        cursor = request.headers.get("last-event-id")
        if cursor and cursor.isdecimal():
            observed_last_event_ids.append(int(cursor))
    return await call_next(request)


app.include_router(auth_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(delivery_router, prefix="/api/v1")
app.include_router(workspace_router, prefix="/api/v1")
app.dependency_overrides[get_auth_engine] = lambda: engine
app.dependency_overrides[get_auth_settings] = lambda: settings
app.dependency_overrides[get_project_engine] = lambda: engine
app.dependency_overrides[get_workspace_engine] = lambda: engine
app.dependency_overrides[get_delivery_service] = lambda: DeliveryService(
    engine, ARTIFACT_ROOT, poll_seconds=0.1
)
app.dependency_overrides[get_content_plan_provider] = lambda: content_provider
app.dependency_overrides[get_code_generation_provider] = lambda: code_provider
app.dependency_overrides[get_code_generation_renderer] = lambda: AcceptingRenderer()
app.dependency_overrides[get_job_signal_publisher] = lambda: publisher


@app.get("/api/v1/health")
def health() -> dict[str, str | int]:
    return {
        "status": "ok",
        "service": "phase8-browser-gate",
        "process_id": os.getpid(),
    }


@app.get("/__phase8_gate__/sse-reconnect-evidence")
def sse_reconnect_evidence() -> dict[str, list[int]]:
    return {"last_event_ids": observed_last_event_ids}


@app.post("/__phase8_gate__/shutdown")
def shutdown_for_restart_test() -> dict[str, bool]:
    def terminate() -> None:
        time.sleep(0.1)
        os._exit(0)

    threading.Thread(target=terminate, daemon=True).start()
    return {"accepted": True}
