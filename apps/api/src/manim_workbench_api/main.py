from typing import Literal

from fastapi import FastAPI
from manim_workbench_contracts import CONTRACT_SCHEMA_VERSION
from pydantic import BaseModel, ConfigDict

from manim_workbench_api.assets.router import router as assets_router
from manim_workbench_api.auth.router import router as auth_router
from manim_workbench_api.code_generation.router import router as code_generation_router
from manim_workbench_api.content_plans.router import router as content_plans_router
from manim_workbench_api.delivery.router import router as delivery_router
from manim_workbench_api.jobs.router import router as jobs_router
from manim_workbench_api.projects.router import router as projects_router
from manim_workbench_api.quality.router import router as quality_router
from manim_workbench_api.web_security import configure_web_security
from manim_workbench_api.workspace.router import router as workspace_router


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"]
    service: Literal["api"]
    contract_schema_version: Literal["1.9"]


app = FastAPI(title="Manim Workbench API", version="0.1.0")
configure_web_security(app)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(assets_router, prefix="/api/v1")
app.include_router(delivery_router, prefix="/api/v1")
app.include_router(workspace_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(content_plans_router, prefix="/api/v1")
app.include_router(code_generation_router, prefix="/api/v1")
app.include_router(quality_router, prefix="/api/v1")


@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="api",
        contract_schema_version=CONTRACT_SCHEMA_VERSION,
    )
