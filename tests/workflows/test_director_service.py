from __future__ import annotations

import json
from collections import deque
from pathlib import Path

import pytest
from manim_workbench_api.content_plans.errors import (
    ContentPlanError,
    ContentPlanErrorCode,
)
from manim_workbench_api.content_plans.models import ProviderResult, ProviderUsage
from manim_workbench_api.workflows.director.repository import DirectorRepository
from manim_workbench_api.workflows.director.service import DirectorPlanningService
from manim_workbench_contracts import (
    DirectorPlanRequest,
    DirectorPlanStatus,
    Language,
    WorkflowStylePreset,
)
from sqlalchemy import Engine

from tests.workflows.test_director_repository import (
    OWNER_A,
    PROJECT_A,
)
from tests.workflows.test_director_repository import (
    engine as _director_engine_fixture,
)


@pytest.fixture
def director_engine(tmp_path: Path) -> Engine:
    return _director_engine_fixture.__wrapped__(tmp_path)


def _request(
    *, style: WorkflowStylePreset = WorkflowStylePreset.DARK_SCIENTIFIC
) -> DirectorPlanRequest:
    return DirectorPlanRequest(
        project_id=PROJECT_A,
        objective="Create a bounded explanation with verified evidence.",
        language=Language.ZH_CN,
        target_duration_seconds=60,
        style_preset=style,
        idempotency_key=f"director-service-{style.value}-0001",
    )


def _candidate(*, confirmation: bool = False) -> str:
    confirmations = (
        [
            {
                "code": "paper_content_required",
                "message": "Provide the paper content.",
                "scene_position": 2,
                "kind": "asset_required",
            }
        ]
        if confirmation
        else []
    )
    return json.dumps(
        {
            "global_brief": {
                "title": "Bounded explanation",
                "language": "zh-CN",
                "target_duration_seconds": 60,
                "aspect_ratio": "16:9",
                "style_preset": "dark_scientific",
                "background": "#10131a",
                "palette": ["#4488ff", "#ffcc22"],
                "notation": {},
                "scientific_parameters": {},
            },
            "scenes": [
                {
                    "title": "Concept",
                    "prompt": "Explain the verified concept.",
                    "pipeline_mode": "teaching",
                    "target_duration_seconds": 30,
                    "asset_requirements": [],
                    "semantic_summary": "Introduce the concept.",
                },
                {
                    "title": "Evidence",
                    "prompt": "Show bounded verified evidence.",
                    "pipeline_mode": "scientific",
                    "target_duration_seconds": 30,
                    "asset_requirements": ["paper content"] if confirmation else [],
                    "semantic_summary": "Show the evidence.",
                },
            ],
            "assumptions": ["Use only verified evidence."],
            "confirmations": confirmations,
        }
    )


class FakeProvider:
    def __init__(self, *results: str | Exception) -> None:
        self.results = deque(results)
        self.calls = 0

    def generate(self, _messages):  # type: ignore[no-untyped-def]
        self.calls += 1
        result = self.results.popleft()
        if isinstance(result, Exception):
            raise result
        return ProviderResult(
            content=result,
            model="director-test-provider",
            request_id=f"request-{self.calls}",
            usage=ProviderUsage(prompt_tokens=100, completion_tokens=50),
        )


def test_ready_plan_persists_provenance_and_replays_without_provider(
    director_engine: Engine,
) -> None:
    provider = FakeProvider(_candidate())
    service = DirectorPlanningService(DirectorRepository(director_engine), provider)
    queued, created = service.create(_request(), OWNER_A)
    assert created is True
    ready = service.execute(queued.id, PROJECT_A, OWNER_A)
    assert ready.status is DirectorPlanStatus.READY
    assert ready.attempt_count == 1
    assert ready.provider_model == "director-test-provider"
    replay, replay_created = service.create(_request(), OWNER_A)
    assert replay_created is False
    assert replay.id == ready.id
    assert service.execute(replay.id, PROJECT_A, OWNER_A) == ready
    assert provider.calls == 1


def test_invalid_schema_gets_one_bounded_repair_then_succeeds(
    director_engine: Engine,
) -> None:
    provider = FakeProvider("{}", _candidate())
    repository = DirectorRepository(director_engine)
    service = DirectorPlanningService(repository, provider)
    queued, _ = service.create(_request(), OWNER_A)

    ready = service.execute(queued.id, PROJECT_A, OWNER_A)

    assert ready.status is DirectorPlanStatus.READY
    assert ready.attempt_count == 2
    assert provider.calls == 2
    assert [attempt.status for attempt in repository.list_attempts(queued.id, OWNER_A)] == [
        "failed",
        "succeeded",
    ]


def test_security_candidate_fails_without_repair_or_workflow_side_effect(
    director_engine: Engine,
) -> None:
    provider = FakeProvider(json.dumps({"source_code": "from manim import Scene"}))
    service = DirectorPlanningService(DirectorRepository(director_engine), provider)
    queued, _ = service.create(_request(), OWNER_A)

    failed = service.execute(queued.id, PROJECT_A, OWNER_A)

    assert failed.status is DirectorPlanStatus.FAILED
    assert failed.error_code == "director_security_violation"
    assert provider.calls == 1
    with director_engine.connect() as connection:
        for table in (
            "video_workflow_versions",
            "scene_block_runs",
            "render_jobs",
            "workflow_artifacts",
        ):
            assert connection.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar_one() == 0


def test_confirmation_draft_stops_without_execution(director_engine: Engine) -> None:
    provider = FakeProvider(_candidate(confirmation=True))
    service = DirectorPlanningService(DirectorRepository(director_engine), provider)
    queued, _ = service.create(_request(), OWNER_A)

    stopped = service.execute(queued.id, PROJECT_A, OWNER_A)

    assert stopped.status is DirectorPlanStatus.NEEDS_CONFIRMATION, stopped.error_code
    assert stopped.error_code == "needs_confirmation"
    assert stopped.draft is not None and stopped.draft.confirmations


def test_provider_configuration_failure_is_terminal_and_style_changes_cache(
    director_engine: Engine,
) -> None:
    provider = FakeProvider(
        ContentPlanError(
            ContentPlanErrorCode.CONFIGURATION_ERROR,
            "provider is not configured",
        )
    )
    service = DirectorPlanningService(DirectorRepository(director_engine), provider)
    queued, _ = service.create(_request(), OWNER_A)
    failed = service.execute(queued.id, PROJECT_A, OWNER_A)
    assert failed.status is DirectorPlanStatus.FAILED
    assert failed.error_code == "configuration_error"

    other_provider = FakeProvider(_candidate())
    other = DirectorPlanningService(DirectorRepository(director_engine), other_provider)
    light, created = other.create(
        _request(style=WorkflowStylePreset.LIGHT_ACADEMIC), OWNER_A
    )
    assert created is True
    assert light.cache_key != queued.cache_key
