from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from manim_workbench_api.quality.reports import QualityReportRepository, QualityReportService
from manim_workbench_api.workspace.dependencies import (
    MutatingPrincipal,
    ReadyPrincipal,
    get_workspace_engine,
)
from sqlalchemy import Engine


def get_quality_report_service(
    engine: Annotated[Engine, Depends(get_workspace_engine)],
) -> QualityReportService:
    return QualityReportService(QualityReportRepository(engine))


QualityService = Annotated[QualityReportService, Depends(get_quality_report_service)]

__all__ = [
    "MutatingPrincipal",
    "QualityService",
    "ReadyPrincipal",
    "get_quality_report_service",
]
