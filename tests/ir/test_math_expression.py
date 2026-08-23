from __future__ import annotations

import inspect

import pytest
from manim_workbench_api.code_generation import math_expression
from manim_workbench_api.code_generation.math_expression import (
    MathExpressionError,
    compile_function_expression,
    compile_function_variants,
)


def compile_required(expression: str):  # type: ignore[no-untyped-def]
    compiled = compile_function_expression(expression)
    assert compiled is not None
    return compiled


def test_compiler_preserves_operator_grouping_and_implicit_constants() -> None:
    assert compile_required("y=(-x)^2").python_expression == "((-x) ** 2)"
    assert compile_required("y=(x^2)^3").python_expression == "((x ** 2) ** 3)"
    assert compile_required("y=2π+sin(x)").python_expression == ("((2 * math.pi) + math.sin(x))")


def test_compiler_extracts_shifted_quadratic_features() -> None:
    features = compile_required("y=(x-1)^2-2").quadratic_features()

    assert features is not None
    vertex_x, vertex_y, roots = features
    assert vertex_x == pytest.approx(1)
    assert vertex_y == pytest.approx(-2)
    assert roots == pytest.approx((1 - 2**0.5, 1 + 2**0.5))


def test_registered_parameter_family_expands_to_bounded_concrete_curves() -> None:
    variants = compile_function_variants("y=kx")

    assert tuple(item.source_expression for item in variants) == ("y=-x", "y=x", "y=2x")
    assert tuple(item.python_expression for item in variants) == ("(-x)", "x", "(2 * x)")


@pytest.mark.parametrize(
    "expression",
    (
        "y=__import__('os').system('id')",
        "y=lambda x: x",
        "y=x**x",
        "y=1/0",
        "y=" + "9" * 400,
    ),
)
def test_compiler_fails_closed_for_executable_or_unbounded_input(expression: str) -> None:
    with pytest.raises(MathExpressionError):
        compile_function_expression(expression)


def test_compiler_implementation_does_not_use_eval_or_lambda() -> None:
    source = inspect.getsource(math_expression)

    assert "eval(" not in source
    assert "lambda " not in source
