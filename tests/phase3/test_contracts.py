from datetime import datetime, timezone
from uuid import uuid4

import pytest
from manim_workbench_contracts.models import (
    Audience,
    ContentPlanScene,
    ContentPlanVersion,
    FormulaStep,
    Language,
    Project,
    PromptVersion,
)
from pydantic import ValidationError

NOW = datetime.now(timezone.utc)


def test_all_project_records_carry_owner_id() -> None:
    from manim_workbench_contracts.models import PROJECT_RECORD_MODELS

    for model in PROJECT_RECORD_MODELS:
        assert "owner_id" in model.model_fields, model.__name__


def test_contracts_reject_undeclared_fields_and_are_frozen() -> None:
    project = Project(id=uuid4(), owner_id=uuid4(), title="Limits", created_at=NOW)

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Project(
            id=uuid4(),
            owner_id=uuid4(),
            title="Limits",
            created_at=NOW,
            arbitrary_parameters={"escape": True},
        )

    with pytest.raises(ValidationError, match="frozen"):
        project.title = "Changed"


def test_version_chain_rules_are_explicit() -> None:
    common = {
        "id": uuid4(),
        "project_id": uuid4(),
        "owner_id": uuid4(),
        "prompt": "Explain the derivative of x squared",
        "created_at": NOW,
    }

    PromptVersion(version=1, parent_version_id=None, **common)

    with pytest.raises(ValidationError, match="first version"):
        PromptVersion(version=1, parent_version_id=uuid4(), **common)

    with pytest.raises(ValidationError, match="later versions"):
        PromptVersion(version=2, parent_version_id=None, **common)


def test_content_plan_contains_required_teaching_structure() -> None:
    plan = ContentPlanVersion(
        id=uuid4(),
        project_id=uuid4(),
        owner_id=uuid4(),
        version=1,
        parent_version_id=None,
        schema_version="1.0",
        title="Derivative of x squared",
        audience=Audience.HIGH_SCHOOL,
        language=Language.ZH_CN,
        target_duration_seconds=90,
        explicit_assumptions=("The learner understands powers.",),
        scenes=(
            ContentPlanScene(
                scene_number=1,
                teaching_goal="Connect the limit definition to the power rule.",
                formula_steps=(
                    FormulaStep(
                        expression=r"f'(x)=\lim_{h\to0}\frac{(x+h)^2-x^2}{h}",
                        explanation="Start from the derivative definition.",
                    ),
                ),
                visual_intent="Highlight cancellation before taking the limit.",
                narration_placeholder="Explain why h may be cancelled before the limit.",
            ),
        ),
        created_at=NOW,
    )

    assert plan.schema_version == "1.0"
    assert plan.scenes[0].formula_steps


def test_contract_enums_do_not_contain_other_escape_value() -> None:
    from manim_workbench_contracts.models import CONTRACT_ENUMS

    for enum_type in CONTRACT_ENUMS:
        values = {str(member.value).lower() for member in enum_type}
        assert "other" not in values, enum_type.__name__
