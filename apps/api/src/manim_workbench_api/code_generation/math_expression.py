"""Fail-closed compilation for the bounded teaching function-expression subset."""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass


class MathExpressionError(ValueError):
    """Raised when teaching content is outside the deterministic expression subset."""


@dataclass(frozen=True, slots=True)
class CompiledFunctionExpression:
    source_expression: str
    python_expression: str
    polynomial_coefficients: tuple[float, ...] | None

    def quadratic_features(self) -> tuple[float, float, tuple[float, ...]] | None:
        coefficients = self.polynomial_coefficients
        if coefficients is None or len(coefficients) != 3 or coefficients[2] == 0:
            return None
        constant, linear, quadratic = coefficients
        vertex_x = -linear / (2 * quadratic)
        vertex_y = constant + linear * vertex_x + quadratic * vertex_x**2
        discriminant = linear**2 - 4 * quadratic * constant
        roots: tuple[float, ...] = ()
        if discriminant >= 0:
            root_delta = math.sqrt(discriminant)
            roots = (
                (-linear - root_delta) / (2 * quadratic),
                (-linear + root_delta) / (2 * quadratic),
            )
        return vertex_x, vertex_y, roots


_FUNCTION_LHS = re.compile(r"^(?:y|f\s*\(\s*x\s*\))$", re.IGNORECASE)
_ALLOWED_CALLS = frozenset({"sin", "cos", "exp", "sqrt"})
_SUPERSCRIPTS = str.maketrans({"²": "**2", "³": "**3", "−": "-", "×": "*", "÷": "/"})


def compile_function_expression(expression: str) -> CompiledFunctionExpression | None:
    """Compile a y=f(x) expression without eval, arbitrary names, or attributes."""

    if "=" not in expression:
        return None
    left, right = expression.split("=", 1)
    if not _FUNCTION_LHS.fullmatch(left.strip()):
        return None
    normalized = _normalize(right)
    try:
        tree = ast.parse(normalized, mode="eval")
    except (SyntaxError, TypeError, ValueError) as error:
        raise MathExpressionError("unsupported function expression") from error
    if sum(1 for _ in ast.walk(tree)) > 96:
        raise MathExpressionError("unsupported function expression")
    _validate(tree.body)
    polynomial = _polynomial(tree.body)
    coefficients = _coefficient_tuple(polynomial) if polynomial is not None else None
    return CompiledFunctionExpression(
        source_expression=expression,
        python_expression=_emit(tree.body),
        polynomial_coefficients=coefficients,
    )


def compile_function_variants(expression: str) -> tuple[CompiledFunctionExpression, ...]:
    """Expand only registered symbolic parameter families into concrete safe curves."""

    compact = re.sub(r"\s+", "", expression).lower()
    if compact in {"y=kx", "f(x)=kx"}:
        variants = ("y=-x", "y=x", "y=2x")
        return tuple(
            compiled
            for variant in variants
            if (compiled := compile_function_expression(variant)) is not None
        )
    compiled = compile_function_expression(expression)
    return (compiled,) if compiled is not None else ()


def _normalize(expression: str) -> str:
    value = expression.translate(_SUPERSCRIPTS).replace("^", "**").strip()
    value = re.sub(r"√\s*\(([^()]*)\)", r"sqrt(\1)", value)
    value = re.sub(r"√\s*([0-9]+(?:\.[0-9]+)?)", r"sqrt(\1)", value)
    value = value.replace("π", "pi")
    value = re.sub(r"(?<=\d)(?=x\b|pi\b|[A-Za-z]+\s*\(|\()", "*", value)
    value = re.sub(r"(?<=x)(?=\()", "*", value)
    value = re.sub(r"(?<=\))(?=x\b|\d|\()", "*", value)
    return value


def _validate(node: ast.AST) -> None:
    if isinstance(node, ast.Constant):
        if type(node.value) not in {int, float}:
            raise MathExpressionError("unsupported function expression")
        try:
            finite = math.isfinite(float(node.value))
        except (OverflowError, TypeError, ValueError) as error:
            raise MathExpressionError("unsupported function expression") from error
        if not finite:
            raise MathExpressionError("unsupported function expression")
        return
    if isinstance(node, ast.Name):
        if node.id not in {"x", "pi"}:
            raise MathExpressionError("unsupported function expression")
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd | ast.USub):
        _validate(node.operand)
        return
    if isinstance(node, ast.BinOp) and isinstance(
        node.op, ast.Add | ast.Sub | ast.Mult | ast.Div | ast.Pow
    ):
        _validate(node.left)
        _validate(node.right)
        if (
            isinstance(node.op, ast.Div)
            and isinstance(node.right, ast.Constant)
            and node.right.value == 0
        ):
            raise MathExpressionError("unsupported function expression")
        if isinstance(node.op, ast.Pow):
            if not isinstance(node.right, ast.Constant) or type(node.right.value) is not int:
                raise MathExpressionError("unsupported function expression")
            if not 0 <= node.right.value <= 4:
                raise MathExpressionError("unsupported function expression")
        return
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id not in _ALLOWED_CALLS or len(node.args) != 1 or node.keywords:
            raise MathExpressionError("unsupported function expression")
        _validate(node.args[0])
        return
    raise MathExpressionError("unsupported function expression")


def _emit(node: ast.AST) -> str:
    if isinstance(node, ast.Constant):
        return repr(node.value)
    if isinstance(node, ast.Name):
        return "math.pi" if node.id == "pi" else node.id
    if isinstance(node, ast.UnaryOp):
        operator = "+" if isinstance(node.op, ast.UAdd) else "-"
        return f"({operator}{_emit(node.operand)})"
    if isinstance(node, ast.BinOp):
        operator = {
            ast.Add: "+",
            ast.Sub: "-",
            ast.Mult: "*",
            ast.Div: "/",
            ast.Pow: "**",
        }[type(node.op)]
        return f"({_emit(node.left)} {operator} {_emit(node.right)})"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return f"math.{node.func.id}({_emit(node.args[0])})"
    raise MathExpressionError("unsupported function expression")


Polynomial = dict[int, float]


def _polynomial(node: ast.AST) -> Polynomial | None:
    if isinstance(node, ast.Constant):
        return {0: float(node.value)}
    if isinstance(node, ast.Name):
        return {1: 1.0} if node.id == "x" else None
    if isinstance(node, ast.UnaryOp):
        value = _polynomial(node.operand)
        if value is None:
            return None
        factor = -1.0 if isinstance(node.op, ast.USub) else 1.0
        return {degree: factor * coefficient for degree, coefficient in value.items()}
    if not isinstance(node, ast.BinOp):
        return None
    left = _polynomial(node.left)
    right = _polynomial(node.right)
    if left is None or right is None:
        return None
    if isinstance(node.op, ast.Add | ast.Sub):
        result = dict(left)
        factor = -1.0 if isinstance(node.op, ast.Sub) else 1.0
        for degree, coefficient in right.items():
            result[degree] = result.get(degree, 0.0) + factor * coefficient
        return _clean(result)
    if isinstance(node.op, ast.Mult):
        return _multiply(left, right)
    if isinstance(node.op, ast.Div):
        if set(right) != {0} or right[0] == 0:
            return None
        return _clean({degree: coefficient / right[0] for degree, coefficient in left.items()})
    if isinstance(node.op, ast.Pow):
        if not isinstance(node.right, ast.Constant) or type(node.right.value) is not int:
            return None
        result: Polynomial = {0: 1.0}
        for _ in range(node.right.value):
            multiplied = _multiply(result, left)
            if multiplied is None:
                return None
            result = multiplied
        return result
    return None


def _multiply(left: Polynomial, right: Polynomial) -> Polynomial | None:
    result: Polynomial = {}
    for left_degree, left_coefficient in left.items():
        for right_degree, right_coefficient in right.items():
            degree = left_degree + right_degree
            if degree > 3:
                return None
            result[degree] = result.get(degree, 0.0) + left_coefficient * right_coefficient
    return _clean(result)


def _clean(polynomial: Polynomial) -> Polynomial:
    return {degree: value for degree, value in polynomial.items() if abs(value) > 1e-12} or {0: 0.0}


def _coefficient_tuple(polynomial: Polynomial) -> tuple[float, ...]:
    degree = max(polynomial)
    return tuple(polynomial.get(index, 0.0) for index in range(degree + 1))
