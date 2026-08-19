from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from manim_workbench_contracts import (
    CodeGenerationCategory,
    CodeGenerationErrorCode,
    CodeGenerationMode,
    CodeGenerationOutcome,
    CodeGenerationRequest,
    CodeGenerationResponse,
    CodeModelResponse,
)
from manim_workbench_contracts.models import CodeVersion
from pydantic import ValidationError


def code_version(*, mode: CodeGenerationMode = CodeGenerationMode.FULL) -> CodeVersion:
    identifier = uuid4()
    return CodeVersion(
        id=identifier,
        project_id=uuid4(),
        owner_id=uuid4(),
        version=1,
        parent_version_id=None,
        created_at=datetime.now(timezone.utc),
        prompt_version_id=uuid4(),
        content_plan_version_id=uuid4(),
        source_code="from manim import Scene\nclass GeneratedScene(Scene):\n    pass\n",
        source_sha256="0" * 64,
        scene_class="GeneratedScene",
        engine="manimce",
        engine_version="0.21.0",
        category=CodeGenerationCategory.FORMULA_DERIVATION,
        generation_mode=mode,
    )


def test_request_forbids_source_and_provider_overrides() -> None:
    with pytest.raises(ValidationError, match="source_code"):
        CodeGenerationRequest(
            project_id=uuid4(),
            owner_id=uuid4(),
            prompt_version_id=uuid4(),
            content_plan_version_id=uuid4(),
            category=CodeGenerationCategory.FORMULA_DERIVATION,
            source_code="print('host')",
        )


def test_model_response_requires_generated_scene_without_markdown() -> None:
    response = CodeModelResponse(
        scene_class="GeneratedScene",
        code="from manim import Scene\nclass GeneratedScene(Scene):\n    pass\n",
    )
    assert response.scene_class == "GeneratedScene"

    with pytest.raises(ValidationError, match="Markdown"):
        CodeModelResponse(scene_class="GeneratedScene", code="```python\npass\n```")


def test_generation_response_is_a_strict_discriminated_payload() -> None:
    ready = CodeGenerationResponse(
        outcome=CodeGenerationOutcome.READY,
        code_version=code_version(),
        attempts_used=1,
        mode=CodeGenerationMode.FULL,
    )
    assert ready.error_code is None

    with pytest.raises(ValidationError, match="failed/paused requires only error_code"):
        CodeGenerationResponse(
            outcome=CodeGenerationOutcome.FAILED,
            code_version=code_version(),
            attempts_used=3,
            mode=CodeGenerationMode.FULL,
            error_code=CodeGenerationErrorCode.ATTEMPT_BUDGET_EXHAUSTED,
        )


def test_degraded_response_requires_deterministic_template_mode() -> None:
    degraded_version = code_version(mode=CodeGenerationMode.DETERMINISTIC_TEMPLATE)
    response = CodeGenerationResponse(
        outcome=CodeGenerationOutcome.DEGRADED,
        code_version=degraded_version,
        attempts_used=0,
        mode=CodeGenerationMode.DETERMINISTIC_TEMPLATE,
    )
    assert response.outcome is CodeGenerationOutcome.DEGRADED
