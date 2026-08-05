from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from manim_workbench_api.code_generation.errors import CodeGenerationError
from manim_workbench_api.code_generation.repair import (
    CategoryPolicy,
    CategoryPolicyState,
)
from manim_workbench_api.code_generation.repository import CodeGenerationRepository
from manim_workbench_contracts import (
    CodeGenerationCategory,
    CodeGenerationErrorCode,
    CodeGenerationMode,
    CodeGenerationRequest,
    CodeModelResponse,
)
from sqlalchemy import Engine, create_engine, text

ROOT = Path(__file__).resolve().parents[3]
OWNER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_OWNER_ID = UUID("00000000-0000-0000-0000-000000000099")
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000002")
PROMPT_ID = UUID("00000000-0000-0000-0000-000000000003")
PLAN_ID = UUID("00000000-0000-0000-0000-000000000004")


def plan_payload() -> dict[str, object]:
    return {
        "schema_version": "1.1",
        "title": "一次函数图像",
        "audience": "high_school",
        "language": "zh-CN",
        "target_duration_seconds": 60,
        "derivation_style": "visual_intuition",
        "explicit_assumptions": ["学习者理解坐标系。"],
        "ambiguities": [],
        "scenes": [
            {
                "scene_number": 1,
                "teaching_goal": "观察斜率变化",
                "formula_steps": [{"expression": "y=kx", "explanation": "固定截距。"}],
                "visual_intent": "显示坐标轴并改变 k。",
                "narration_placeholder": "比较正负斜率。",
            }
        ],
    }


def migrated_engine(tmp_path: Path) -> Engine:
    database_path = tmp_path / "phase7-repository.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id, email, created_at) VALUES (:id, :email, :created_at)"),
            {"id": str(OWNER_ID), "email": "owner@example.com", "created_at": "2026-08-05"},
        )
        connection.execute(
            text(
                "INSERT INTO projects (id, owner_id, title, created_at) "
                "VALUES (:id, :owner_id, 'Phase 7', '2026-08-05')"
            ),
            {"id": str(PROJECT_ID), "owner_id": str(OWNER_ID)},
        )
        connection.execute(
            text(
                "INSERT INTO prompt_versions "
                "(id, project_id, owner_id, version, parent_version_id, created_at, prompt) "
                "VALUES (:id, :project_id, :owner_id, 1, NULL, '2026-08-05', '一次函数')"
            ),
            {"id": str(PROMPT_ID), "project_id": str(PROJECT_ID), "owner_id": str(OWNER_ID)},
        )
        connection.execute(
            text(
                "INSERT INTO content_plan_versions "
                "(id, project_id, owner_id, version, parent_version_id, created_at, "
                "schema_version, content_json) VALUES "
                "(:id, :project_id, :owner_id, 1, NULL, '2026-08-05', '1.1', :content_json)"
            ),
            {
                "id": str(PLAN_ID),
                "project_id": str(PROJECT_ID),
                "owner_id": str(OWNER_ID),
                "content_json": json.dumps(plan_payload(), ensure_ascii=False),
            },
        )
    return engine


def request(*, owner_id: UUID = OWNER_ID) -> CodeGenerationRequest:
    return CodeGenerationRequest(
        project_id=PROJECT_ID,
        owner_id=owner_id,
        prompt_version_id=PROMPT_ID,
        content_plan_version_id=PLAN_ID,
        category=CodeGenerationCategory.FUNCTION_VISUALIZATION,
    )


def test_load_input_requires_prompt_plan_project_and_owner_match(tmp_path: Path) -> None:
    repository = CodeGenerationRepository(migrated_engine(tmp_path))
    loaded = repository.load_input(request())
    assert loaded.content_plan.id == PLAN_ID
    assert loaded.content_plan.schema_version == "1.1"

    with pytest.raises(CodeGenerationError) as caught:
        repository.load_input(request(owner_id=OTHER_OWNER_ID))
    assert caught.value.code is CodeGenerationErrorCode.CONTENT_PLAN_NOT_FOUND


def test_failed_attempt_stores_only_hashes_and_does_not_create_code_version(
    tmp_path: Path,
) -> None:
    engine = migrated_engine(tmp_path)
    repository = CodeGenerationRepository(engine)
    repository.record_failed_attempt(
        request(),
        attempt_number=1,
        error_code=CodeGenerationErrorCode.COMPILE_FAILED,
        provider_model="deepseek-v4-flash",
        candidate_sha256="a" * 64,
        diagnostic_sha256="b" * 64,
    )

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM code_versions")).scalar_one() == 0
        row = connection.execute(
            text(
                "SELECT error_code, candidate_sha256, diagnostic_sha256 "
                "FROM generation_attempts"
            )
        ).one()
    assert tuple(row) == ("compile_failed", "a" * 64, "b" * 64)


def test_success_creates_immutable_code_version_with_provenance(tmp_path: Path) -> None:
    engine = migrated_engine(tmp_path)
    repository = CodeGenerationRepository(engine)
    source = "from manim import Scene\nclass GeneratedScene(Scene):\n    pass\n"
    version = repository.save_success(
        request(),
        response=CodeModelResponse(
            scene_class="GeneratedScene",
            code=source,
            assumptions=("只显示一个示例。",),
        ),
        attempt_number=2,
        mode=CodeGenerationMode.FULL,
        prompt_template_version="phase7-code-v1",
        provider_model="deepseek-v4-flash",
    )

    assert version.version == 1
    assert version.source_code == source
    assert version.category is CodeGenerationCategory.FUNCTION_VISUALIZATION
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT category, generation_mode, scene_class, assumptions_json "
                "FROM code_versions"
            )
        ).one()
        attempts = connection.execute(
            text("SELECT stage, status, output_version_id FROM generation_attempts")
        ).one()
    assert tuple(row[:3]) == ("function_visualization", "full", "GeneratedScene")
    assert json.loads(row[3]) == ["只显示一个示例。"]
    assert attempts == ("repair", "succeeded", str(version.id))


def test_category_policies_persist_independently_and_global_pause_is_explicit(
    tmp_path: Path,
) -> None:
    repository = CodeGenerationRepository(migrated_engine(tmp_path))
    policies = repository.load_category_policies()
    assert all(policy.state is CategoryPolicyState.ACTIVE for policy in policies.values())

    repository.save_category_policy(
        CodeGenerationCategory.FORMULA_DERIVATION,
        CategoryPolicy(
            state=CategoryPolicyState.DEGRADED,
            consecutive_failed_quality_rounds=2,
        ),
    )
    loaded = repository.load_category_policies()
    assert loaded[CodeGenerationCategory.FORMULA_DERIVATION].state is CategoryPolicyState.DEGRADED
    assert loaded[CodeGenerationCategory.FUNCTION_VISUALIZATION].state is CategoryPolicyState.ACTIVE

    repository.pause_all_categories()
    assert all(
        policy.state is CategoryPolicyState.PAUSED
        for policy in repository.load_category_policies().values()
    )
