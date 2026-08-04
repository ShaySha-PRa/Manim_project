from typing import Literal

from fastapi import FastAPI
from manim_workbench_contracts import CONTRACT_SCHEMA_VERSION
from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"]
    service: Literal["api"]
    contract_schema_version: Literal["1.1"]


app = FastAPI(title="Manim Workbench API", version="0.1.0")


@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="api",
        contract_schema_version=CONTRACT_SCHEMA_VERSION,
    )
