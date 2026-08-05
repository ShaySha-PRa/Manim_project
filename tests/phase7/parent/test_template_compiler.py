from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from manim_workbench_api.code_generation.security import validate_source_security
from manim_workbench_api.code_generation.template_compiler import (
    compile_deterministic_template,
    degrade_mathtex_to_text,
)
from manim_workbench_contracts import (
    Audience,
    CodeGenerationCategory,
    ContentPlanScene,
    ContentPlanVersion,
    DerivationStyle,
    FormulaStep,
    Language,
)


def test_latex_degradation_rewrites_only_manim_mathtex_calls_to_text() -> None:
    source = '''\
from manim import MathTex as Formula, Scene

class GeneratedScene(Scene):
    def construct(self):
        value = r"x^2=4"
        equation = Formula(value, color="blue")
        pair = Formula("x=2", "x=-2", arg_separator=" or ")
        self.add(equation, pair)
'''

    degraded = degrade_mathtex_to_text(source)

    assert "from manim import" in degraded
    assert "Text" in degraded.splitlines()[0]
    assert "Formula(" not in degraded
    assert "Text(value" in degraded
    assert "Text('x=2 x=-2'" in degraded
    assert degraded.count("font='Noto Sans CJK SC'") == 2
    assert "arg_separator" not in degraded
    assert validate_source_security(degraded).allowed is True


def test_deterministic_template_uses_the_bundled_cjk_font_for_all_text() -> None:
    plan = ContentPlanVersion(
        id=uuid4(),
        project_id=uuid4(),
        owner_id=uuid4(),
        version=1,
        parent_version_id=None,
        created_at=datetime.now(timezone.utc),
        schema_version="1.1",
        title="一元二次方程",
        audience=Audience.HIGH_SCHOOL,
        language=Language.ZH_CN,
        target_duration_seconds=60,
        derivation_style=DerivationStyle.STEP_BY_STEP,
        explicit_assumptions=(),
        ambiguities=(),
        scenes=(
            ContentPlanScene(
                scene_number=1,
                teaching_goal="推导求根公式",
                formula_steps=(
                    FormulaStep(expression="x² = 4", explanation="两边开平方"),
                ),
                visual_intent="逐步展示",
                narration_placeholder="解释每一步",
            ),
        ),
    )

    response = compile_deterministic_template(
        plan, CodeGenerationCategory.FORMULA_DERIVATION
    )

    text_lines = [line for line in response.code.splitlines() if " = Text(" in line]
    assert text_lines
    assert all('font="Noto Sans CJK SC"' in line for line in text_lines)
