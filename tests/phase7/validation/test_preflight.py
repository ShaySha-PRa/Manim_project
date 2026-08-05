from __future__ import annotations

import pytest
from manim_workbench_api.code_generation.validation import (
    Diagnostic,
    preflight_source,
    sanitize_diagnostic,
)
from manim_workbench_contracts import CodeGenerationErrorCode

VALID_SOURCE = "from manim import Scene\n\nclass GeneratedScene(Scene):\n    pass\n"


def test_preflight_accepts_one_direct_generated_scene_without_importing_source() -> None:
    source = (
        "import module_that_must_not_be_imported\n\n"
        "class GeneratedScene(Scene):\n"
        "    pass\n"
    )

    report = preflight_source(source)

    assert report.ok is True
    assert report.diagnostic is None


def test_preflight_reports_syntax_errors_as_repairable_compile_failures() -> None:
    report = preflight_source("class GeneratedScene(Scene)\n    pass\n")

    assert report.ok is False
    assert report.diagnostic is not None
    assert report.diagnostic.stage == "compile"
    assert report.diagnostic.error_code is CodeGenerationErrorCode.COMPILE_FAILED
    assert report.diagnostic.error_type == "SyntaxError"
    assert report.diagnostic.line_number == 1
    assert report.diagnostic.repairable is True


@pytest.mark.parametrize(
    "source",
    (
        "from manim import Scene\n",
        "from manim import Scene\n\nclass OtherScene(Scene):\n    pass\n",
        "from manim import Scene\n\nclass GeneratedScene(object):\n    pass\n",
        "from manim import Scene\n\nclass GeneratedScene(Scene, object):\n    pass\n",
        (
            "from manim import Scene\n\nclass GeneratedScene(Scene):\n    pass\n\n"
            "class Helper:\n    pass\n"
        ),
        (
            "from manim import Scene\n\nclass GeneratedScene(Scene):\n    pass\n\n"
            "class GeneratedScene(Scene):\n    pass\n"
        ),
    ),
)
def test_preflight_requires_exactly_one_direct_generated_scene(source: str) -> None:
    report = preflight_source(source)

    assert report.ok is False
    assert report.diagnostic is not None
    assert report.diagnostic.stage == "scene_structure"
    assert report.diagnostic.error_code is CodeGenerationErrorCode.SCENE_STRUCTURE_INVALID
    assert report.diagnostic.error_type == "SceneStructureError"
    assert report.diagnostic.repairable is True


@pytest.mark.parametrize(
    ("error_code", "expected_repairable"),
    (
        (CodeGenerationErrorCode.INVALID_MODEL_RESPONSE, True),
        (CodeGenerationErrorCode.COMPILE_FAILED, True),
        (CodeGenerationErrorCode.SCENE_STRUCTURE_INVALID, True),
        (CodeGenerationErrorCode.RENDER_FAILED, True),
        (CodeGenerationErrorCode.SECURITY_POLICY_VIOLATION, False),
        (CodeGenerationErrorCode.PROVIDER_AUTHENTICATION, False),
        (CodeGenerationErrorCode.PROVIDER_CONFIGURATION, False),
        (CodeGenerationErrorCode.PROVIDER_UNAVAILABLE, False),
        (CodeGenerationErrorCode.SANDBOX_TIMEOUT, False),
        (CodeGenerationErrorCode.SANDBOX_RESOURCE_LIMIT, False),
        (CodeGenerationErrorCode.INTERNAL_ERROR, False),
    ),
)
def test_sanitize_diagnostic_classifies_repairability_from_stable_error_code(
    error_code: CodeGenerationErrorCode, expected_repairable: bool
) -> None:
    diagnostic = sanitize_diagnostic(
        "upstream detail",
        error_code=error_code,
        stage="supplied",
    )

    assert diagnostic.error_code is error_code
    assert diagnostic.repairable is expected_repairable


def test_sanitize_diagnostic_redacts_secrets_locations_urls_and_bounds_output() -> None:
    diagnostic = sanitize_diagnostic(
        "\n".join(
            (
                "Traceback from /home/developer/projects/Manim_project/.env:7",
                r"Windows path C:\\Users\\Developer\\secrets.txt",
                "See https://example.test/private?token=visible",
                "Authorization: Bearer deeply-secret-token-value",
                "DEEPSEEK_API_KEY=sk-very-secret-key-material",
                "api_key: another-secret-value",
                *(f"detail line {number}" for number in range(30)),
            )
        ),
        error_code=CodeGenerationErrorCode.COMPILE_FAILED,
        stage="compile",
        line_number=7,
    )

    assert diagnostic.line_number == 7
    assert diagnostic.repairable is True
    assert "/home/developer" not in diagnostic.message
    assert r"C:\\Users\\Developer" not in diagnostic.message
    assert "https://example.test" not in diagnostic.message
    assert "deeply-secret-token-value" not in diagnostic.message
    assert "sk-very-secret-key-material" not in diagnostic.message
    assert "another-secret-value" not in diagnostic.message
    assert len(diagnostic.message.splitlines()) <= 20
    assert len(diagnostic.message) <= 4000


def test_sanitize_diagnostic_replaces_a_diagnostic_without_changing_its_classification() -> None:
    original = Diagnostic(
        stage="compile",
        error_code=CodeGenerationErrorCode.COMPILE_FAILED,
        error_type="SyntaxError",
        message="failed at /tmp/generated.py with Bearer value-to-remove",
        line_number=3,
        repairable=False,
    )

    sanitized = sanitize_diagnostic(original)

    assert sanitized.error_code is CodeGenerationErrorCode.COMPILE_FAILED
    assert sanitized.repairable is True
    assert "/tmp/generated.py" not in sanitized.message
    assert "value-to-remove" not in sanitized.message


def test_sanitize_diagnostic_preserves_bounded_head_and_error_tail() -> None:
    lines = [
        "renderer started" + "x" * 5_000,
        *(f"progress {index}" for index in range(30)),
        "TypeError: bad",
    ]

    diagnostic = sanitize_diagnostic(
        "\n".join(lines),
        error_code=CodeGenerationErrorCode.RENDER_FAILED,
        stage="render",
    )

    assert diagnostic.message.splitlines()[0].startswith("renderer ")
    assert "[TRUNCATED]" in diagnostic.message
    assert diagnostic.message.splitlines()[-1] == "TypeError: bad"
    assert len(diagnostic.message.splitlines()) == 20
