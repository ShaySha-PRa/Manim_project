from datetime import datetime, timezone
from uuid import uuid4

import pytest
from manim_workbench_contracts import (
    CONTRACT_SCHEMA_VERSION,
    ApiErrorDetail,
    AuthenticatedUser,
    LoginRequest,
    LoginResponse,
    PipelineStage,
    ProjectUpdateRequest,
)
from pydantic import ValidationError


def test_phase8_contract_schema_is_frozen_at_1_4() -> None:
    assert CONTRACT_SCHEMA_VERSION == "1.11"


def test_browser_login_contract_does_not_accept_owner_or_session_token() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(
            email="teacher@example.test",
            password="correct horse battery staple",
            owner_id=str(uuid4()),
        )

    response = LoginResponse(
        user=AuthenticatedUser(
            id=uuid4(),
            email="teacher@example.test",
            must_change_password=True,
            created_at=datetime.now(timezone.utc),
        ),
        csrf_token="c" * 43,
        expires_at=datetime.now(timezone.utc),
    )
    assert not hasattr(response, "session_token")


def test_project_patch_requires_a_real_change() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        ProjectUpdateRequest()


def test_pipeline_errors_have_a_bounded_stage() -> None:
    detail = ApiErrorDetail(
        code="render_failed",
        message="The preview render failed.",
        stage=PipelineStage.PREVIEW_RENDER,
    )
    assert detail.stage is PipelineStage.PREVIEW_RENDER
