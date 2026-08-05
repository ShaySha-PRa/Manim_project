from __future__ import annotations

from sqlalchemy import Engine

from manim_workbench_api.database import create_database_engine

from .models import ContentPlanProvider


def get_content_plan_engine() -> Engine:
    return create_database_engine()


def get_content_plan_provider() -> ContentPlanProvider:
    from .provider import DeepSeekProvider

    return DeepSeekProvider()
