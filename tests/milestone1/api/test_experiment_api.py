from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
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
from manim_workbench_api.database import create_database_engine
from manim_workbench_api.experiments.dependencies import get_experiment_engine
from manim_workbench_api.experiments.repository import ExperimentRepository
from manim_workbench_api.experiments.router import router as experiments_router
from manim_workbench_api.projects.repository import ProjectRepository
from manim_workbench_contracts import AssumptionSource, ExperimentPatchOperation
from sqlalchemy import Engine

ROOT = Path(__file__).resolve().parents[3]
ORIGIN = "http://localhost:3000"
PASSWORD = "initial password 123"
NEW_PASSWORD = "replacement password 456"

PRE_M1_PATHS = frozenset(
    {
        "/api/v1/artifacts/{artifact_id}",
        "/api/v1/artifacts/{artifact_id}/download",
        "/api/v1/auth/change-password",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/session",
        "/api/v1/code-generations",
        "/api/v1/code-versions/{code_version_id}",
        "/api/v1/content-plans/generate",
        "/api/v1/health",
        "/api/v1/internal/render-jobs/recoverable",
        "/api/v1/internal/render-jobs/{job_id}/cancelled",
        "/api/v1/internal/render-jobs/{job_id}/claim",
        "/api/v1/internal/render-jobs/{job_id}/complete",
        "/api/v1/internal/render-jobs/{job_id}/fail",
        "/api/v1/internal/render-jobs/{job_id}/heartbeat",
        "/api/v1/internal/render-jobs/{job_id}/start",
        "/api/v1/projects",
        "/api/v1/projects/{project_id}",
        "/api/v1/projects/{project_id}/content-plan-versions",
        "/api/v1/projects/{project_id}/prompt-versions",
        "/api/v1/projects/{project_id}/quality-reports",
        "/api/v1/quality-reports/{report_id}",
        "/api/v1/quality-reports/{report_id}/diagnostics",
        "/api/v1/quality-reports/{report_id}/human-rating",
        "/api/v1/render-jobs",
        "/api/v1/render-jobs/{job_id}",
        "/api/v1/render-jobs/{job_id}/cancel",
        "/api/v1/render-jobs/{job_id}/events",
        "/api/v1/render-jobs/{job_id}/quality-report",
        "/api/v1/workspace/code-versions/{code_version_id}/source",
        "/api/v1/workspace/projects/{project_id}/code-generations",
        "/api/v1/workspace/projects/{project_id}/content-plans/generate",
        "/api/v1/workspace/projects/{project_id}/render-jobs",
        "/api/v1/workspace/render-jobs/{job_id}",
        "/api/v1/workspace/render-jobs/{job_id}/artifacts",
        "/api/v1/workspace/render-jobs/{job_id}/cancel",
    }
)

EXPERIMENT_PATHS = frozenset(
    {
        "/api/v1/projects/{project_id}/experiments",
        "/api/v1/experiments/{experiment_id}",
        "/api/v1/experiments/{experiment_id}/draft",
        "/api/v1/experiments/{experiment_id}/versions",
        "/api/v1/experiments/{experiment_id}/patch-proposals",
        "/api/v1/experiments/{experiment_id}/patch-proposals/{proposal_id}/apply",
        "/api/v1/experiments/{experiment_id}/patch-proposals/{proposal_id}/reject",
    }
)


@dataclass
class ExperimentApi:
    app: FastAPI
    client_a: TestClient
    client_b: TestClient
    engine: Engine
    owner_a: UUID
    owner_b: UUID
    project_a: UUID
    project_b: UUID
    csrf_a: str
    csrf_b: str


def _migrated_engine(tmp_path: Path) -> Engine:
    database_path = tmp_path / "experiments-api.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    return create_database_engine(f"sqlite:///{database_path}")


def _ready_client(client: TestClient, email: str) -> str:
    login = client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": email, "password": PASSWORD},
    )
    assert login.status_code == 200, login.text
    changed = client.post(
        "/api/v1/auth/change-password",
        headers={"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]},
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert changed.status_code == 200, changed.text
    return str(changed.json()["csrf_token"])


def _mutation_headers(csrf_token: str) -> dict[str, str]:
    return {"Origin": ORIGIN, "X-CSRF-Token": csrf_token}


def _create_experiment(api: ExperimentApi, title: str = "Wave experiment") -> dict[str, object]:
    response = api.client_a.post(
        f"/api/v1/projects/{api.project_a}/experiments",
        headers=_mutation_headers(api.csrf_a),
        json={"title": title, "domain_kind": "geometry"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _seed_proposal(
    api: ExperimentApi,
    experiment_id: UUID,
    *,
    expected_revision: int,
    operation: ExperimentPatchOperation,
) -> UUID:
    proposal = ExperimentRepository(api.engine).create_patch_proposal(
        experiment_id,
        api.owner_a,
        expected_revision=expected_revision,
        operations=(operation,),
        assumptions=(),
        source=AssumptionSource.MODEL,
    )
    return proposal.id


@pytest.fixture
def experiment_api(tmp_path: Path) -> ExperimentApi:
    engine = _migrated_engine(tmp_path)
    service = AuthService(engine)
    owner_a = service.create_user("owner-a@example.test", PASSWORD).user_id
    owner_b = service.create_user("owner-b@example.test", PASSWORD).user_id
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(experiments_router, prefix="/api/v1")
    app.dependency_overrides[get_auth_engine] = lambda: engine
    app.dependency_overrides[get_auth_settings] = lambda: AuthSettings(
        allowed_origins=frozenset({ORIGIN}), cookie_secure=False
    )
    app.dependency_overrides[get_experiment_engine] = lambda: engine
    client_a = TestClient(app)
    client_b = TestClient(app)
    csrf_a = _ready_client(client_a, "owner-a@example.test")
    csrf_b = _ready_client(client_b, "owner-b@example.test")
    projects = ProjectRepository(engine)
    project_a = projects.create_project(owner_a, "Owner A project")
    project_b = projects.create_project(owner_b, "Owner B project")
    try:
        yield ExperimentApi(
            app=app,
            client_a=client_a,
            client_b=client_b,
            engine=engine,
            owner_a=owner_a,
            owner_b=owner_b,
            project_a=project_a.id,
            project_b=project_b.id,
            csrf_a=csrf_a,
            csrf_b=csrf_b,
        )
    finally:
        client_a.close()
        client_b.close()
        engine.dispose()


def test_create_list_get_and_initial_draft_use_owner_scoped_contracts(
    experiment_api: ExperimentApi,
) -> None:
    api = experiment_api
    created = [_create_experiment(api, f"Experiment {number}") for number in range(3)]
    experiment_id = UUID(str(created[0]["id"]))

    draft = api.client_a.get(f"/api/v1/experiments/{experiment_id}/draft")
    detail = api.client_a.get(f"/api/v1/experiments/{experiment_id}")
    all_rows = api.client_a.get(f"/api/v1/projects/{api.project_a}/experiments")
    first_page = api.client_a.get(
        f"/api/v1/projects/{api.project_a}/experiments", params={"limit": 1}
    )
    second_page = api.client_a.get(
        f"/api/v1/projects/{api.project_a}/experiments",
        params={"limit": 1, "cursor": first_page.json()["cursor"]},
    )
    boundary_page = api.client_a.get(
        f"/api/v1/projects/{api.project_a}/experiments", params={"limit": 100}
    )

    assert draft.status_code == detail.status_code == all_rows.status_code == 200
    assert draft.json()["revision"] == 1
    assert draft.json()["model_spec"]["domain_kind"] == "geometry"
    assert detail.json() == created[0]
    assert [item["id"] for item in all_rows.json()["items"]] == sorted(
        item["id"] for item in created
    )
    assert first_page.json()["cursor"] == first_page.json()["items"][0]["id"]
    assert second_page.status_code == boundary_page.status_code == 200
    assert len(second_page.json()["items"]) == 1
    assert len(boundary_page.json()["items"]) == 3


def test_draft_compare_and_swap_and_idempotent_versions_are_exposed(
    experiment_api: ExperimentApi,
) -> None:
    api = experiment_api
    experiment_id = UUID(str(_create_experiment(api)["id"]))

    updated = api.client_a.patch(
        f"/api/v1/experiments/{experiment_id}/draft",
        headers=_mutation_headers(api.csrf_a),
        json={"expected_revision": 1, "visualization": {"theme": "dark"}},
    )
    stale = api.client_a.patch(
        f"/api/v1/experiments/{experiment_id}/draft",
        headers=_mutation_headers(api.csrf_a),
        json={"expected_revision": 1, "visualization": {"theme": "light"}},
    )
    first_version = api.client_a.post(
        f"/api/v1/experiments/{experiment_id}/versions",
        headers=_mutation_headers(api.csrf_a),
        json={"expected_revision": 2},
    )
    repeated_version = api.client_a.post(
        f"/api/v1/experiments/{experiment_id}/versions",
        headers=_mutation_headers(api.csrf_a),
        json={"expected_revision": 2},
    )
    next_draft = api.client_a.patch(
        f"/api/v1/experiments/{experiment_id}/draft",
        headers=_mutation_headers(api.csrf_a),
        json={"expected_revision": 2, "visualization": {"theme": "light"}},
    )
    second_version = api.client_a.post(
        f"/api/v1/experiments/{experiment_id}/versions",
        headers=_mutation_headers(api.csrf_a),
        json={"expected_revision": 3},
    )
    first_page = api.client_a.get(
        f"/api/v1/experiments/{experiment_id}/versions", params={"limit": 1}
    )
    second_page = api.client_a.get(
        f"/api/v1/experiments/{experiment_id}/versions",
        params={"limit": 1, "cursor": first_page.json()["cursor"]},
    )
    maximum_page = api.client_a.get(
        f"/api/v1/experiments/{experiment_id}/versions", params={"limit": 100}
    )

    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert stale.status_code == 409
    assert stale.json() == _error("experiment_revision_conflict")
    assert first_version.status_code == 201
    assert repeated_version.status_code == 200
    assert repeated_version.json()["id"] == first_version.json()["id"]
    assert next_draft.status_code == 200
    assert second_version.status_code == 201
    assert first_page.status_code == second_page.status_code == maximum_page.status_code == 200
    assert first_page.json()["items"][0]["version"] == 2
    assert second_page.json()["items"][0]["version"] == 1
    assert [item["version"] for item in maximum_page.json()["items"]] == [2, 1]


def test_patch_proposal_list_apply_reject_and_error_lifecycle(
    experiment_api: ExperimentApi,
) -> None:
    api = experiment_api
    experiment_id = UUID(str(_create_experiment(api)["id"]))
    valid_proposal = _seed_proposal(
        api,
        experiment_id,
        expected_revision=1,
        operation=ExperimentPatchOperation(
            kind="add", path="/visualization/mode", value="interactive"
        ),
    )
    list_only_proposal = _seed_proposal(
        api,
        experiment_id,
        expected_revision=1,
        operation=ExperimentPatchOperation(
            kind="add", path="/visualization/list-only", value=True
        ),
    )
    final_list_proposal = _seed_proposal(
        api,
        experiment_id,
        expected_revision=1,
        operation=ExperimentPatchOperation(
            kind="add", path="/visualization/third", value=True
        ),
    )
    listed = api.client_a.get(f"/api/v1/experiments/{experiment_id}/patch-proposals")
    first_list_page = api.client_a.get(
        f"/api/v1/experiments/{experiment_id}/patch-proposals", params={"limit": 1}
    )
    second_list_page = api.client_a.get(
        f"/api/v1/experiments/{experiment_id}/patch-proposals",
        params={"limit": 1, "cursor": first_list_page.json()["cursor"]},
    )
    maximum_list_page = api.client_a.get(
        f"/api/v1/experiments/{experiment_id}/patch-proposals", params={"limit": 100}
    )
    applied = api.client_a.post(
        f"/api/v1/experiments/{experiment_id}/patch-proposals/{valid_proposal}/apply",
        headers=_mutation_headers(api.csrf_a),
        json={"expected_revision": 1},
    )
    applied_again = api.client_a.post(
        f"/api/v1/experiments/{experiment_id}/patch-proposals/{valid_proposal}/apply",
        headers=_mutation_headers(api.csrf_a),
        json={"expected_revision": 1},
    )
    reject_proposal = _seed_proposal(
        api,
        experiment_id,
        expected_revision=2,
        operation=ExperimentPatchOperation(
            kind="add", path="/visualization/label", value="review"
        ),
    )
    rejected = api.client_a.post(
        f"/api/v1/experiments/{experiment_id}/patch-proposals/{reject_proposal}/reject",
        headers=_mutation_headers(api.csrf_a),
        json={"expected_revision": 2, "reason": "Not needed"},
    )
    rejected_again = api.client_a.post(
        f"/api/v1/experiments/{experiment_id}/patch-proposals/{reject_proposal}/reject",
        headers=_mutation_headers(api.csrf_a),
        json={"expected_revision": 2},
    )
    invalid_proposal = _seed_proposal(
        api,
        experiment_id,
        expected_revision=2,
        operation=ExperimentPatchOperation(
            kind="replace", path="/visualization/missing", value="bad"
        ),
    )
    invalid = api.client_a.post(
        f"/api/v1/experiments/{experiment_id}/patch-proposals/{invalid_proposal}/apply",
        headers=_mutation_headers(api.csrf_a),
        json={"expected_revision": 2},
    )
    stale_proposal = _seed_proposal(
        api,
        experiment_id,
        expected_revision=1,
        operation=ExperimentPatchOperation(
            kind="add", path="/visualization/stale", value=True
        ),
    )
    stale = api.client_a.post(
        f"/api/v1/experiments/{experiment_id}/patch-proposals/{stale_proposal}/apply",
        headers=_mutation_headers(api.csrf_a),
        json={"expected_revision": 1},
    )
    other_experiment_id = UUID(str(_create_experiment(api, "Other experiment")["id"]))
    other_proposal = _seed_proposal(
        api,
        other_experiment_id,
        expected_revision=1,
        operation=ExperimentPatchOperation(
            kind="add", path="/visualization/mode", value="other"
        ),
    )
    wrong_experiment = api.client_a.post(
        f"/api/v1/experiments/{experiment_id}/patch-proposals/{other_proposal}/apply",
        headers=_mutation_headers(api.csrf_a),
        json={"expected_revision": 2},
    )

    assert listed.status_code == 200
    proposal_ids = (valid_proposal, list_only_proposal, final_list_proposal)
    assert [item["id"] for item in listed.json()["items"]] == sorted(
        str(proposal_id) for proposal_id in proposal_ids
    )
    for item in listed.json()["items"]:
        assert item["operations"][0]["kind"] == "add"
        assert "operation" not in item["operations"][0]
    assert first_list_page.json()["cursor"] == first_list_page.json()["items"][0]["id"]
    assert second_list_page.status_code == maximum_list_page.status_code == 200
    assert len(second_list_page.json()["items"]) == 1
    assert len(maximum_list_page.json()["items"]) == 3
    assert applied.status_code == 200
    assert applied.json()["revision"] == 2
    assert applied.json()["visualization"] == {"mode": "interactive"}
    assert applied_again.status_code == 409
    assert applied_again.json() == _error("experiment_proposal_resolved")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["resolved_at"] is not None
    assert rejected_again.status_code == 409
    assert rejected_again.json() == _error("experiment_proposal_resolved")
    assert invalid.status_code == 422
    assert invalid.json() == _error("experiment_patch_invalid")
    assert stale.status_code == 409
    assert stale.json() == _error("experiment_revision_conflict")
    assert wrong_experiment.status_code == 404
    assert wrong_experiment.json() == _error("experiment_proposal_not_found")


def test_cross_owner_and_missing_resources_have_identical_responses(
    experiment_api: ExperimentApi,
) -> None:
    api = experiment_api
    experiment_id = UUID(str(_create_experiment(api)["id"]))
    proposal_id = _seed_proposal(
        api,
        experiment_id,
        expected_revision=1,
        operation=ExperimentPatchOperation(
            kind="add", path="/visualization/mode", value="interactive"
        ),
    )
    missing_project = uuid4()
    missing_experiment = uuid4()
    mutation_headers = _mutation_headers(api.csrf_b)

    cross_project = api.client_b.get(f"/api/v1/projects/{api.project_a}/experiments")
    absent_project = api.client_b.get(f"/api/v1/projects/{missing_project}/experiments")
    cross_create = api.client_b.post(
        f"/api/v1/projects/{api.project_a}/experiments",
        headers=mutation_headers,
        json={"title": "Denied"},
    )
    absent_create = api.client_b.post(
        f"/api/v1/projects/{missing_project}/experiments",
        headers=mutation_headers,
        json={"title": "Denied"},
    )
    cross_draft_update = api.client_b.patch(
        f"/api/v1/experiments/{experiment_id}/draft",
        headers=mutation_headers,
        json={"expected_revision": 1, "visualization": {}},
    )
    absent_draft_update = api.client_b.patch(
        f"/api/v1/experiments/{missing_experiment}/draft",
        headers=mutation_headers,
        json={"expected_revision": 1, "visualization": {}},
    )
    cross_version = api.client_b.post(
        f"/api/v1/experiments/{experiment_id}/versions",
        headers=mutation_headers,
        json={"expected_revision": 1},
    )
    absent_version = api.client_b.post(
        f"/api/v1/experiments/{missing_experiment}/versions",
        headers=mutation_headers,
        json={"expected_revision": 1},
    )

    for suffix in ("", "/draft", "/versions", "/patch-proposals"):
        cross = api.client_b.get(f"/api/v1/experiments/{experiment_id}{suffix}")
        absent = api.client_b.get(f"/api/v1/experiments/{missing_experiment}{suffix}")
        assert cross.status_code == absent.status_code == 404
        assert cross.json() == absent.json() == _error("experiment_not_found")

    for action in ("apply", "reject"):
        cross = api.client_b.post(
            f"/api/v1/experiments/{experiment_id}/patch-proposals/{proposal_id}/{action}",
            headers=mutation_headers,
            json={"expected_revision": 1},
        )
        absent = api.client_b.post(
            f"/api/v1/experiments/{missing_experiment}/patch-proposals/{proposal_id}/{action}",
            headers=mutation_headers,
            json={"expected_revision": 1},
        )
        assert cross.status_code == absent.status_code == 404
        assert cross.json() == absent.json() == _error("experiment_not_found")

    assert cross_project.status_code == absent_project.status_code == 404
    assert cross_project.json() == absent_project.json() == _error("project_not_found")
    assert cross_create.status_code == absent_create.status_code == 404
    assert cross_create.json() == absent_create.json() == _error("project_not_found")
    assert cross_draft_update.status_code == absent_draft_update.status_code == 404
    assert cross_draft_update.json() == absent_draft_update.json() == _error("experiment_not_found")
    assert cross_version.status_code == absent_version.status_code == 404
    assert cross_version.json() == absent_version.json() == _error("experiment_not_found")


def test_real_auth_chain_enforces_ready_session_origin_and_csrf(
    experiment_api: ExperimentApi,
) -> None:
    api = experiment_api
    experiment_id = UUID(str(_create_experiment(api)["id"]))
    anonymous = TestClient(api.app)
    unready = TestClient(api.app)
    AuthService(api.engine).create_user("unready@example.test", PASSWORD)
    login = unready.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": "unready@example.test", "password": PASSWORD},
    )
    assert login.status_code == 200
    unready_headers = {"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]}
    missing_origin = api.client_a.post(
        f"/api/v1/projects/{api.project_a}/experiments",
        headers={"X-CSRF-Token": api.csrf_a},
        json={"title": "Denied"},
    )
    wrong_origin = api.client_a.post(
        f"/api/v1/projects/{api.project_a}/experiments",
        headers={"Origin": "https://attacker.example", "X-CSRF-Token": api.csrf_a},
        json={"title": "Denied"},
    )
    missing_csrf = api.client_a.post(
        f"/api/v1/projects/{api.project_a}/experiments",
        headers={"Origin": ORIGIN},
        json={"title": "Denied"},
    )
    try:
        assert anonymous.get(f"/api/v1/experiments/{experiment_id}").status_code == 401
        assert anonymous.post(
            f"/api/v1/projects/{api.project_a}/experiments", json={"title": "Denied"}
        ).status_code == 403
        assert unready.get(f"/api/v1/experiments/{experiment_id}").status_code == 403
        assert unready.post(
            f"/api/v1/projects/{api.project_a}/experiments",
            headers=unready_headers,
            json={"title": "Denied"},
        ).status_code == 403
        assert (
            missing_origin.status_code
            == wrong_origin.status_code
            == missing_csrf.status_code
            == 403
        )
        assert missing_origin.json() == wrong_origin.json() == missing_csrf.json() == _error(
            "authorization_failed", message="Request was not authorized."
        )
    finally:
        anonymous.close()
        unready.close()


def test_validation_uses_the_stable_envelope_and_rejects_identity_injection(
    experiment_api: ExperimentApi,
) -> None:
    api = experiment_api
    experiment_id = UUID(str(_create_experiment(api)["id"]))
    headers = _mutation_headers(api.csrf_a)
    invalid_responses = (
        api.client_a.get("/api/v1/experiments/not-a-uuid"),
        api.client_a.get("/api/v1/projects/not-a-uuid/experiments"),
        api.client_a.get(
            f"/api/v1/projects/{api.project_a}/experiments", params={"cursor": "bad"}
        ),
        api.client_a.get(f"/api/v1/projects/{api.project_a}/experiments", params={"limit": 0}),
        api.client_a.get(f"/api/v1/projects/{api.project_a}/experiments", params={"limit": 101}),
        api.client_a.get(f"/api/v1/experiments/{experiment_id}/versions", params={"cursor": 0}),
        api.client_a.get(f"/api/v1/experiments/{experiment_id}/versions", params={"limit": 0}),
        api.client_a.get(f"/api/v1/experiments/{experiment_id}/versions", params={"limit": 101}),
        api.client_a.get(
            f"/api/v1/experiments/{experiment_id}/patch-proposals", params={"cursor": "bad"}
        ),
        api.client_a.get(
            f"/api/v1/experiments/{experiment_id}/patch-proposals", params={"limit": 0}
        ),
        api.client_a.get(
            f"/api/v1/experiments/{experiment_id}/patch-proposals", params={"limit": 101}
        ),
        api.client_a.post(
            f"/api/v1/projects/{api.project_a}/experiments",
            headers=headers,
            json={"title": "Injected", "owner_id": str(api.owner_b)},
        ),
        api.client_a.patch(
            f"/api/v1/experiments/{experiment_id}/draft",
            headers=headers,
            json={"expected_revision": 1},
        ),
        api.client_a.patch(
            f"/api/v1/experiments/{experiment_id}/draft",
            headers=headers,
            json={"expected_revision": 1, "visualization": None},
        ),
        api.client_a.patch(
            f"/api/v1/experiments/{experiment_id}/draft",
            headers=headers,
            json={"expected_revision": 1, "project_id": str(api.project_b), "visualization": {}},
        ),
        api.client_a.post(
            f"/api/v1/experiments/{experiment_id}/versions",
            headers=headers,
            json={"expected_revision": 1, "owner_id": str(api.owner_b)},
        ),
    )

    for response in invalid_responses:
        assert response.status_code == 422
        assert response.json() == _error("validation_error")


def test_concurrent_apply_and_reject_have_one_winner_and_stable_loser(
    experiment_api: ExperimentApi,
) -> None:
    api = experiment_api
    experiment_id = UUID(str(_create_experiment(api)["id"]))
    proposal_id = _seed_proposal(
        api,
        experiment_id,
        expected_revision=1,
        operation=ExperimentPatchOperation(
            kind="add", path="/visualization/mode", value="interactive"
        ),
    )
    session_token = api.client_a.cookies.get("manim_workbench_session")
    headers = _mutation_headers(api.csrf_a)

    def submit(action: str) -> tuple[int, dict[str, object]]:
        client = TestClient(api.app)
        client.cookies.set("manim_workbench_session", session_token)
        try:
            response = client.post(
                f"/api/v1/experiments/{experiment_id}/patch-proposals/{proposal_id}/{action}",
                headers=headers,
                json={"expected_revision": 1},
            )
            return response.status_code, response.json()
        finally:
            client.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(submit, ("apply", "reject")))

    assert sorted(status_code for status_code, _body in outcomes) == [200, 409]
    assert next(body for status_code, body in outcomes if status_code == 409) == _error(
        "experiment_proposal_resolved"
    )


def test_openapi_adds_only_the_ten_experiment_operations_and_health_16() -> None:
    from manim_workbench_api.main import app

    schema = app.openapi()
    paths = set(schema["paths"])
    experiment_operations = {
        (path, method)
        for path in EXPERIMENT_PATHS
        for method in schema["paths"][path]
        if method in {"get", "post", "patch", "delete"}
    }

    assert PRE_M1_PATHS <= paths
    assert paths - PRE_M1_PATHS == EXPERIMENT_PATHS
    assert experiment_operations == {
        ("/api/v1/projects/{project_id}/experiments", "get"),
        ("/api/v1/projects/{project_id}/experiments", "post"),
        ("/api/v1/experiments/{experiment_id}", "get"),
        ("/api/v1/experiments/{experiment_id}/draft", "get"),
        ("/api/v1/experiments/{experiment_id}/draft", "patch"),
        ("/api/v1/experiments/{experiment_id}/versions", "get"),
        ("/api/v1/experiments/{experiment_id}/versions", "post"),
        ("/api/v1/experiments/{experiment_id}/patch-proposals", "get"),
        ("/api/v1/experiments/{experiment_id}/patch-proposals/{proposal_id}/apply", "post"),
        ("/api/v1/experiments/{experiment_id}/patch-proposals/{proposal_id}/reject", "post"),
    }
    version_responses = schema["paths"]["/api/v1/experiments/{experiment_id}/versions"][
        "post"
    ]["responses"]
    assert {"200", "201"} <= set(version_responses)
    for status_code in ("200", "201"):
        assert version_responses[status_code]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ExperimentVersion"
        }
    assert version_responses["200"]["description"] == "Existing version with identical content."
    assert schema["paths"]["/api/v1/health"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"] == "#/components/schemas/HealthResponse"
    assert schema["components"]["schemas"]["HealthResponse"]["properties"][
        "contract_schema_version"
    ]["const"] == "1.6"


def _error(code: str, message: str = "Request payload is invalid.") -> dict[str, object]:
    messages = {
        "project_not_found": "Project was not found.",
        "experiment_not_found": "Experiment was not found.",
        "experiment_proposal_not_found": "Experiment patch proposal was not found.",
        "experiment_revision_conflict": "Experiment revision is no longer current.",
        "experiment_proposal_resolved": "Experiment patch proposal is already resolved.",
        "experiment_patch_invalid": "Experiment patch proposal is invalid.",
    }
    return {"error": {"code": code, "message": messages.get(code, message)}}
