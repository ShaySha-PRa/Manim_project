from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError

import pytest
from manim_workbench_api.code_generation.security import (
    SecurityFinding,
    SourceSecurityReport,
    complete_allowlisted_manim_imports,
    validate_source_security,
)

FORMULA_SCENE = '''\
from manim import DOWN, UP, MathTex, Scene, Text, Transform, Write

class GeneratedScene(Scene):
    def construct(self) -> None:
        title = Text("Complete the square", font_size=36).to_edge(UP)
        equation = MathTex(r"x^2+6x+5=0", font_size=66)
        next_equation = MathTex(r"(x+3)^2=4", font_size=66)
        self.play(Write(title), Write(equation), run_time=0.75)
        self.play(Transform(equation, next_equation), run_time=0.65)
        self.wait(0.35)
'''

FUNCTION_SCENE = '''\
import math
import numpy as np
from manim import BLUE, UP, Axes, Create, MathTex, Scene, Write

class GeneratedScene(Scene):
    def construct(self) -> None:
        def exponential(x):
            return math.exp(x)

        title = MathTex(r"y=e^x").scale(0.8).to_edge(UP)
        axes = Axes(x_range=[-2, 2, 1], y_range=[-1, 5, 1], tips=False)
        graph = axes.plot(exponential, x_range=[-1, 1], color=BLUE)
        samples = np.linspace(-1, 1, 5)
        label = MathTex(str(math.floor(samples[0])))
        self.play(Write(title), Create(axes), Create(graph), Write(label), run_time=0.8)
'''


def finding_codes(report: SourceSecurityReport) -> set[str]:
    return {finding.code for finding in report.findings}


@pytest.mark.parametrize("source", [FORMULA_SCENE])
def test_valid_reference_like_formula_scene_is_allowed(source: str) -> None:
    report = validate_source_security(source)

    assert report.allowed is True
    assert report.findings == ()
    assert report.source_sha256 == hashlib.sha256(source.encode("utf-8")).hexdigest()


def test_valid_reference_like_function_scene_is_allowed() -> None:
    report = validate_source_security(FUNCTION_SCENE)

    assert report.allowed is True
    assert report.findings == ()


def test_report_and_findings_are_immutable() -> None:
    report = validate_source_security(FORMULA_SCENE)

    with pytest.raises(FrozenInstanceError):
        report.allowed = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        SecurityFinding(code="x", message="x").code = "y"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("source", "expected_code"),
    [
        (
            "import os as math\nfrom manim import Scene\n"
            "class GeneratedScene(Scene):\n    def construct(self):\n        math.system('id')\n",
            "forbidden_import",
        ),
        (
            "from manim import Scene\n"
            "class GeneratedScene(Scene):\n    def construct(self):\n"
            "        getattr(self, '__class__')\n",
            "forbidden_reflection",
        ),
        (
            "from manim import Scene\n"
            "class GeneratedScene(Scene):\n    def construct(self):\n"
            "        __import__('socket')\n",
            "forbidden_name",
        ),
        (
            "from manim import Scene\n"
            "class GeneratedScene(Scene):\n    def construct(self):\n        open('/etc/passwd')\n",
            "forbidden_name",
        ),
        (
            "from manim import Scene\n"
            "class GeneratedScene(Scene):\n    def construct(self):\n"
            "        __builtins__.__import__('os')\n",
            "forbidden_dunder",
        ),
        (
            "from manim import Scene\n"
            "class GeneratedScene(Scene):\n    def construct(self):\n"
            "        __import__('subprocess').run(['id'])\n",
            "forbidden_name",
        ),
        (
            "from manim import Scene\n"
            "class GeneratedScene(Scene):\n"
            "    @staticmethod\n    def construct():\n        pass\n",
            "forbidden_decorator",
        ),
    ],
)
def test_rejects_aliasing_reflection_dynamic_import_and_host_apis(
    source: str, expected_code: str
) -> None:
    report = validate_source_security(source)

    assert report.allowed is False
    assert expected_code in finding_codes(report)


def test_rejects_unknown_manim_api_and_non_generated_scene_class() -> None:
    source = '''\
from manim import Scene, TotallyUnknownMobject

class OtherScene(Scene):
    def construct(self):
        self.play(TotallyUnknownMobject())
'''

    report = validate_source_security(source)

    assert report.allowed is False
    assert {"unknown_manim_symbol", "invalid_scene_class"} <= finding_codes(report)
    unknown = next(
        finding for finding in report.findings if finding.code == "unknown_manim_symbol"
    )
    assert unknown.symbol == "TotallyUnknownMobject"


def test_rejects_nested_container_payloads_and_source_size_exhaustion() -> None:
    nested = "[" * 81 + "0" + "]" * 81
    container_source = (
        "from manim import Scene\n"
        "class GeneratedScene(Scene):\n"
        "    def construct(self):\n"
        f"        payload = {nested}\n"
    )
    oversized_source = "x" * 200_001

    assert "container_depth_exceeded" in finding_codes(validate_source_security(container_source))
    assert "source_too_large" in finding_codes(validate_source_security(oversized_source))


def test_rejects_dynamic_dictionary_unpacking() -> None:
    source = '''\
from manim import Scene

class GeneratedScene(Scene):
    def construct(self):
        payload = {**{"safe": 1}}
'''

    report = validate_source_security(source)

    assert report.allowed is False
    assert "forbidden_container_unpacking" in finding_codes(report)


def test_parse_errors_fail_closed_and_preserve_a_source_hash() -> None:
    source = "from manim import Scene\nclass GeneratedScene(Scene)\n"

    report = validate_source_security(source)

    assert report.allowed is False
    assert "parse_error" in finding_codes(report)
    assert report.findings[0].line == 2
    assert report.source_sha256 == hashlib.sha256(source.encode("utf-8")).hexdigest()


def test_common_read_only_manim_geometry_methods_are_allowlisted() -> None:
    source = '''\
from manim import Scene, Text

class GeneratedScene(Scene):
    def construct(self):
        label = Text("safe")
        center = label.get_center()
        left = label.get_left()
        label.move_to(center).align_to(left)
'''

    assert validate_source_security(source).allowed is True


def test_bounded_formatting_unpacking_and_local_destructuring_are_allowlisted() -> None:
    source = '''\
from manim import GrowArrow, NumberLine, Scene, Text, VGroup

class GeneratedScene(Scene):
    def construct(self):
        left, right = 1, 2
        labels = [Text(f"x={value}") for value in range(left, right + 1)]
        group = VGroup(*labels)
        line = NumberLine()
        point = line.n2p(left)
        animations = []
        animations.append(GrowArrow(line))
        self.add(group)
'''

    assert validate_source_security(source).allowed is True


def test_unknown_symbol_is_available_for_internal_diagnostics_only() -> None:
    source = '''\
from manim import Scene

class GeneratedScene(Scene):
    def construct(self):
        MysteryObject()
'''
    report = validate_source_security(source)
    unknown = next(finding for finding in report.findings if finding.code == "unknown_call")
    assert unknown.symbol == "MysteryObject"


def test_only_missing_allowlisted_manim_imports_are_completed_then_revalidated() -> None:
    source = '''\
from manim import Scene as SafeScene, Text

class GeneratedScene(SafeScene):
    def construct(self):
        title = Text("safe").to_edge(UP)
        self.add(title)
'''
    report = validate_source_security(source)

    normalized = complete_allowlisted_manim_imports(source, report)

    assert "Scene as SafeScene" in normalized
    assert "UP" in normalized.splitlines()[0]
    assert validate_source_security(normalized).allowed is True


def test_import_completion_never_changes_forbidden_or_unknown_symbols() -> None:
    source = '''\
import os
from manim import Scene

class GeneratedScene(Scene):
    def construct(self):
        MysteryObject()
'''
    report = validate_source_security(source)

    assert complete_allowlisted_manim_imports(source, report) == source
