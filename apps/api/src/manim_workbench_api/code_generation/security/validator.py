"""Static, non-executing safety validation for generated Manim scenes."""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass
from typing import Final

MAX_SOURCE_CHARACTERS: Final = 200_000
MAX_AST_NODES: Final = 12_000
MAX_CONTAINER_ITEMS: Final = 2_000
MAX_CONTAINER_DEPTH: Final = 80
MAX_FINDINGS: Final = 32
_IMAGE_ASSET_PATH = re.compile(r"^/input/assets/[0-9a-f]{64}\.png$")
_ARRAY_ASSET_PATH = re.compile(r"^/input/assets/[0-9a-f]{64}\.(npz|npy)$")
_ALLOWED_SCENE_BASES: Final = frozenset(
    {"manim:Scene", "manim:MovingCameraScene", "manim:ThreeDScene"}
)

_FORBIDDEN_MODULES: Final = frozenset(
    {
        "asyncio",
        "builtins",
        "ctypes",
        "httpx",
        "importlib",
        "marshal",
        "multiprocessing",
        "os",
        "pathlib",
        "pickle",
        "requests",
        "shutil",
        "signal",
        "socket",
        "subprocess",
        "sys",
        "tempfile",
        "threading",
        "urllib",
    }
)
_FORBIDDEN_NAMES: Final = frozenset(
    {
        "__import__",
        "breakpoint",
        "compile",
        "eval",
        "exec",
        "exit",
        "input",
        "open",
        "quit",
    }
)
_REFLECTION_NAMES: Final = frozenset(
    {
        "delattr",
        "dir",
        "getattr",
        "globals",
        "hasattr",
        "help",
        "id",
        "locals",
        "object",
        "setattr",
        "super",
        "type",
        "vars",
    }
)
_MANIM_SYMBOLS: Final = frozenset(
    {
        "AnimationGroup",
        "Angle",
        "Arc",
        "Arrow",
        "Axes",
        "BLUE",
        "Brace",
        "Circle",
        "Create",
        "Cube",
        "DARK_BLUE",
        "DARK_GRAY",
        "DARK_GREEN",
        "DARK_RED",
        "DEGREES",
        "DashedLine",
        "DashedVMobject",
        "DecimalNumber",
        "Dot",
        "DOWN",
        "FadeIn",
        "FadeOut",
        "GRAY",
        "GRAY_A",
        "GRAY_B",
        "GREEN",
        "GrowArrow",
        "IN",
        "ImageMobject",
        "Indicate",
        "LEFT",
        "LaggedStart",
        "Line",
        "MathTex",
        "MovingCameraScene",
        "NumberLine",
        "NumberPlane",
        "ORANGE",
        "ORIGIN",
        "OUT",
        "PI",
        "PURPLE",
        "Polygon",
        "Rectangle",
        "RIGHT",
        "RED",
        "ReplacementTransform",
        "Restore",
        "RightAngle",
        "Scene",
        "Sphere",
        "Square",
        "Succession",
        "Surface",
        "SurroundingRectangle",
        "TAU",
        "Text",
        "ThreeDAxes",
        "ThreeDScene",
        "Transform",
        "TransformMatchingTex",
        "Triangle",
        "UL",
        "UP",
        "VGroup",
        "ValueTracker",
        "WHITE",
        "Write",
        "YELLOW",
        "always_redraw",
        "linear",
        "smooth",
        "there_and_back",
    }
)
_MATH_SYMBOLS: Final = frozenset(
    {
        "ceil",
        "cos",
        "e",
        "exp",
        "fabs",
        "floor",
        "log",
        "pi",
        "pow",
        "sin",
        "sqrt",
        "tan",
        "tau",
    }
)
_NUMPY_SYMBOLS: Final = frozenset(
    {
        "abs",
        "array",
        "clip",
        "cos",
        "exp",
        "linspace",
        "load",
        "maximum",
        "minimum",
        "pi",
        "sin",
        "sqrt",
        "tan",
    }
)
_SAFE_BUILTINS: Final = frozenset(
    {"abs", "enumerate", "float", "int", "len", "max", "min", "range", "round", "str", "sum", "zip"}
)
_MANIM_MEMBER_NAMES: Final = frozenset(
    {
        "add",
        "add_coordinates",
        "add_fixed_in_frame_mobjects",
        "align_to",
        "animate",
        "append",
        "arrange",
        "begin_ambient_camera_rotation",
        "c2p",
        "camera",
        "copy",
        "frame",
        "get_bottom",
        "get_center",
        "get_end",
        "get_axis_labels",
        "get_graph_label",
        "get_left",
        "get_riemann_rectangles",
        "get_right",
        "get_start",
        "get_top",
        "get_value",
        "move_to",
        "mobjects",
        "n2p",
        "next_to",
        "plot",
        "play",
        "remove",
        "reverse",
        "rotate",
        "save_state",
        "scale",
        "set_camera_orientation",
        "set_color",
        "set_fill",
        "set_height",
        "set_opacity",
        "set_stroke",
        "set_value",
        "shift",
        "stop_ambient_camera_rotation",
        "to_edge",
        "to_corner",
        "wait",
    }
)
_CONTAINER_NODES: Final = (ast.List, ast.Tuple, ast.Set, ast.Dict)
_ALLOWED_GENERIC_NODES: Final = (
    ast.Constant,
    ast.Name,
    ast.Attribute,
    ast.Call,
    ast.keyword,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Dict,
    ast.Subscript,
    ast.Slice,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.ListComp,
    ast.comprehension,
    ast.JoinedStr,
    ast.FormattedValue,
    ast.Starred,
    ast.Load,
    ast.Store,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Not,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
)


@dataclass(frozen=True, slots=True)
class SecurityFinding:
    """A stable, source-free static security rejection reason."""

    code: str
    message: str
    line: int | None = None
    column: int | None = None
    symbol: str | None = None


@dataclass(frozen=True, slots=True)
class SourceSecurityReport:
    """Immutable decision returned before any compilation or sandbox work."""

    allowed: bool
    findings: tuple[SecurityFinding, ...]
    source_sha256: str


def validate_source_security(source: str) -> SourceSecurityReport:
    """Validate untrusted source without importing, compiling, or executing it."""
    if not isinstance(source, str):
        return _report("", (SecurityFinding("invalid_source", "source must be text"),))

    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if len(source) > MAX_SOURCE_CHARACTERS:
        return SourceSecurityReport(
            allowed=False,
            findings=(SecurityFinding("source_too_large", "source exceeds the fixed size limit"),),
            source_sha256=source_sha256,
        )

    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as error:
        return SourceSecurityReport(
            allowed=False,
            findings=(
                SecurityFinding(
                    "parse_error",
                    "source cannot be parsed safely",
                    line=error.lineno,
                    column=error.offset,
                ),
            ),
            source_sha256=source_sha256,
        )
    except (MemoryError, RecursionError, ValueError, TypeError):
        return SourceSecurityReport(
            allowed=False,
            findings=(SecurityFinding("parse_error", "source cannot be parsed safely"),),
            source_sha256=source_sha256,
        )
    except Exception:
        return SourceSecurityReport(
            allowed=False,
            findings=(SecurityFinding("validator_internal_error", "security validation failed"),),
            source_sha256=source_sha256,
        )

    try:
        bounds_findings = _validate_bounds(tree)
        if bounds_findings:
            return SourceSecurityReport(
                allowed=False,
                findings=tuple(bounds_findings),
                source_sha256=source_sha256,
            )
        visitor = _SecurityVisitor()
        visitor.visit(tree)
        return SourceSecurityReport(
            allowed=not visitor.findings,
            findings=tuple(visitor.findings),
            source_sha256=source_sha256,
        )
    except Exception:
        return SourceSecurityReport(
            allowed=False,
            findings=(SecurityFinding("validator_internal_error", "security validation failed"),),
            source_sha256=source_sha256,
        )


def complete_allowlisted_manim_imports(
    source: str, report: SourceSecurityReport
) -> str:
    """Add only omitted, already-allowlisted Manim symbols to an existing import."""
    missing = {
        finding.symbol
        for finding in report.findings
        if finding.code in {"unknown_call", "unknown_name"}
        and finding.symbol in _MANIM_SYMBOLS
    }
    if not missing:
        return source
    try:
        tree = ast.parse(source, mode="exec")
    except (SyntaxError, ValueError, TypeError):
        return source
    imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "manim" and node.level == 0
    ]
    if not imports or any(alias.name == "*" for node in imports for alias in node.names):
        return source
    target = imports[0]
    directly_imported = {
        alias.name for node in imports for alias in node.names if alias.asname is None
    }
    existing_tokens = {
        f"{alias.name} as {alias.asname}" if alias.asname else alias.name
        for alias in target.names
    }
    replacement = "from manim import " + ", ".join(
        sorted(existing_tokens | (missing - directly_imported))
    )
    lines = source.splitlines(keepends=True)
    start = sum(len(line) for line in lines[: target.lineno - 1]) + target.col_offset
    end = sum(len(line) for line in lines[: target.end_lineno - 1]) + target.end_col_offset
    normalized = source[:start] + replacement + source[end:]
    return normalized if len(normalized) <= MAX_SOURCE_CHARACTERS else source


def _report(source: str, findings: tuple[SecurityFinding, ...]) -> SourceSecurityReport:
    return SourceSecurityReport(
        allowed=False,
        findings=findings,
        source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
    )


def _validate_bounds(tree: ast.AST) -> list[SecurityFinding]:
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        return [SecurityFinding("ast_too_large", "source exceeds the fixed AST node limit")]

    for node in nodes:
        if isinstance(node, _CONTAINER_NODES) and _container_size(node) > MAX_CONTAINER_ITEMS:
            return [
                SecurityFinding(
                    "container_too_large", "source exceeds the fixed literal container limit"
                )
            ]

    stack: list[tuple[ast.AST, int]] = [(tree, 0)]
    while stack:
        node, depth = stack.pop()
        next_depth = depth + 1 if isinstance(node, _CONTAINER_NODES) else depth
        if next_depth > MAX_CONTAINER_DEPTH:
            return [
                SecurityFinding(
                    "container_depth_exceeded", "source exceeds the fixed literal nesting limit"
                )
            ]
        stack.extend((child, next_depth) for child in ast.iter_child_nodes(node))
    return []


def _container_size(node: ast.List | ast.Tuple | ast.Set | ast.Dict) -> int:
    return len(node.keys) if isinstance(node, ast.Dict) else len(node.elts)


class _SecurityVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.findings: list[SecurityFinding] = []
        self._aliases: dict[str, str] = {}
        self._scopes: list[set[str]] = [set()]
        self._class_count = 0
        self._generated_scene_count = 0

    def _finding(
        self,
        node: ast.AST,
        code: str,
        message: str,
        *,
        symbol: str | None = None,
    ) -> None:
        if len(self.findings) >= MAX_FINDINGS:
            return
        self.findings.append(
            SecurityFinding(
                code=code,
                message=message,
                line=getattr(node, "lineno", None),
                column=getattr(node, "col_offset", None),
                symbol=symbol,
            )
        )

    def visit_Module(self, node: ast.Module) -> None:  # noqa: N802
        body = _without_docstring(node.body)
        for statement in body:
            if isinstance(statement, ast.Import | ast.ImportFrom):
                self.visit(statement)
            elif isinstance(statement, ast.Assign | ast.AnnAssign):
                self._visit_top_level_constant(statement)
            elif isinstance(statement, ast.ClassDef):
                self.visit(statement)
            else:
                self._finding(
                    statement, "forbidden_top_level", "top-level statement is not allowed"
                )
        if self._class_count != 1 or self._generated_scene_count != 1:
            self._finding(
                node, "invalid_scene_class", "exactly one GeneratedScene is required"
            )

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for imported in node.names:
            if (
                imported.name in _FORBIDDEN_MODULES
                or imported.name.split(".", 1)[0] in _FORBIDDEN_MODULES
            ):
                self._finding(imported, "forbidden_import", "module import is not allowed")
                continue
            if imported.name not in {"math", "numpy"}:
                self._finding(imported, "unknown_import", "module import is not allowed")
                continue
            local_name = imported.asname or imported.name
            if _is_dunder(local_name):
                self._finding(imported, "forbidden_dunder", "dunder aliases are not allowed")
                continue
            self._aliases[local_name] = imported.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.level != 0 or node.module not in {"manim", "math", "numpy"}:
            self._finding(
                node, "forbidden_import", "relative or unapproved imports are not allowed"
            )
            return
        allowed = _allowed_symbols_for_module(node.module)
        for imported in node.names:
            if imported.name == "*":
                if node.module != "manim":
                    self._finding(
                        imported, "forbidden_import", "only Manim star imports are allowed"
                    )
                else:
                    for symbol in _MANIM_SYMBOLS:
                        self._aliases.setdefault(symbol, f"manim:{symbol}")
                continue
            if imported.name not in allowed:
                code = "unknown_manim_symbol" if node.module == "manim" else "unknown_import_symbol"
                self._finding(
                    imported,
                    code,
                    "imported API is not allowlisted",
                    symbol=imported.name,
                )
                continue
            local_name = imported.asname or imported.name
            if _is_dunder(local_name):
                self._finding(imported, "forbidden_dunder", "dunder aliases are not allowed")
                continue
            self._aliases[local_name] = f"{node.module}:{imported.name}"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self._class_count += 1
        if node.name != "GeneratedScene" or not self._has_scene_base(node):
            self._finding(
                node,
                "invalid_scene_class",
                "class must be GeneratedScene with an allowed Scene base",
            )
        else:
            self._generated_scene_count += 1
        if node.decorator_list:
            self._finding(node, "forbidden_decorator", "decorators are not allowed")
        if len(node.bases) != 1 or node.keywords:
            self._finding(node, "invalid_scene_class", "scene must have one direct Scene base")

        body = _without_docstring(node.body)
        constructs = [statement for statement in body if isinstance(statement, ast.FunctionDef)]
        if len(constructs) != 1 or not constructs or constructs[0].name != "construct":
            self._finding(node, "invalid_scene_structure", "scene must contain only construct")
            return
        self._visit_function(constructs[0], require_self=True)

    def _visit_top_level_constant(self, node: ast.Assign | ast.AnnAssign) -> None:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not all(isinstance(target, ast.Name) for target in targets) or node.value is None:
            self._finding(node, "forbidden_top_level", "only named literal constants are allowed")
            return
        if isinstance(node, ast.AnnAssign) and node.annotation is not None:
            self._finding(node, "forbidden_top_level", "top-level annotations are not allowed")
            return
        if not _is_literal(node.value):
            self._finding(node, "forbidden_top_level", "top-level constants must be literals")
            return
        for target in targets:
            assert isinstance(target, ast.Name)
            self._declare(target)

    def _has_scene_base(self, node: ast.ClassDef) -> bool:
        if len(node.bases) != 1 or not isinstance(node.bases[0], ast.Name):
            return False
        return self._aliases.get(node.bases[0].id) in _ALLOWED_SCENE_BASES

    def _visit_function(self, node: ast.FunctionDef, *, require_self: bool) -> None:
        if node.decorator_list:
            self._finding(node, "forbidden_decorator", "decorators are not allowed")
        if not _valid_function_signature(node, require_self=require_self):
            self._finding(node, "invalid_function_signature", "function signature is not allowed")
        self._validate_annotation(node.returns)
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            self._validate_annotation(argument.annotation)
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)

        local_names = {argument.arg for argument in (*node.args.posonlyargs, *node.args.args)}
        local_names.update(argument.arg for argument in node.args.kwonlyargs)
        self._scopes.append(local_names)
        self._visit_block(_without_docstring(node.body))
        self._scopes.pop()

    def _validate_annotation(self, annotation: ast.expr | None) -> None:
        if annotation is None:
            return
        if isinstance(annotation, ast.Constant) and annotation.value is None:
            return
        if isinstance(annotation, ast.Name) and self._aliases.get(annotation.id, "").startswith(
            "manim:"
        ):
            return
        self._finding(annotation, "forbidden_annotation", "annotation is not allowlisted")

    def _visit_block(self, statements: list[ast.stmt]) -> None:
        local_functions = {
            statement.name for statement in statements if isinstance(statement, ast.FunctionDef)
        }
        self._scopes[-1].update(local_functions)
        for statement in statements:
            self.visit(statement)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._visit_function(node, require_self=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._finding(node, "forbidden_async", "async functions are not allowed")

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        if not all(_is_assignable_target(target) for target in node.targets):
            self._finding(node, "invalid_assignment", "only local name assignments are allowed")
        for target in node.targets:
            self._declare_target(target)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        self._finding(node, "forbidden_annotation", "variable annotations are not allowed")

    def visit_AugAssign(self, node: ast.AugAssign) -> None:  # noqa: N802
        if not isinstance(node.target, ast.Name):
            self._finding(node, "invalid_assignment", "only local name assignments are allowed")
        self.visit(node.target)
        self.visit(node.value)

    def visit_Expr(self, node: ast.Expr) -> None:  # noqa: N802
        if not isinstance(node.value, ast.Call):
            self._finding(node, "unsupported_syntax", "expression statement is not allowed")
            return
        self.visit(node.value)

    def visit_For(self, node: ast.For) -> None:  # noqa: N802
        self._declare_target(node.target)
        self.visit(node.iter)
        self._visit_block(node.body)
        self._visit_block(node.orelse)

    def visit_ListComp(self, node: ast.ListComp) -> None:  # noqa: N802
        self._scopes.append(set())
        for generator in node.generators:
            if generator.is_async:
                self._finding(
                    generator,
                    "forbidden_async",
                    "async comprehensions are not allowed",
                )
            self.visit(generator.iter)
            self._declare_target(generator.target)
            for condition in generator.ifs:
                self.visit(condition)
        self.visit(node.elt)
        self._scopes.pop()

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        self.visit(node.test)
        self._visit_block(node.body)
        self._visit_block(node.orelse)

    def visit_Return(self, node: ast.Return) -> None:  # noqa: N802
        if node.value is not None:
            self.visit(node.value)

    def visit_Pass(self, node: ast.Pass) -> None:  # noqa: N802
        return

    def visit_Break(self, node: ast.Break) -> None:  # noqa: N802
        return

    def visit_Continue(self, node: ast.Continue) -> None:  # noqa: N802
        return

    def visit_Global(self, node: ast.Global) -> None:  # noqa: N802
        self._finding(node, "forbidden_scope", "global declarations are not allowed")

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:  # noqa: N802
        self._finding(node, "forbidden_scope", "nonlocal declarations are not allowed")

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        self._finding(node, "forbidden_lambda", "lambda expressions are not allowed")

    def visit_Yield(self, node: ast.Yield) -> None:  # noqa: N802
        self._finding(node, "forbidden_yield", "yield expressions are not allowed")

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:  # noqa: N802
        self._finding(node, "forbidden_yield", "yield expressions are not allowed")

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if node.id in _FORBIDDEN_NAMES:
            self._finding(node, "forbidden_name", "unsafe builtins are not allowed")
        elif node.id in _REFLECTION_NAMES:
            self._finding(node, "forbidden_reflection", "reflection APIs are not allowed")
        elif _is_dunder(node.id):
            self._finding(node, "forbidden_dunder", "dunder names are not allowed")
        elif isinstance(node.ctx, ast.Load) and not self._is_known_name(node.id):
            self._finding(
                node,
                "unknown_name",
                "name is not allowlisted",
                symbol=node.id,
            )

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if _is_dunder(node.attr):
            self._finding(node, "forbidden_dunder", "dunder attributes are not allowed")
        elif node.attr in _REFLECTION_NAMES or node.attr in {"mro", "__subclasses__"}:
            self._finding(node, "forbidden_reflection", "reflection attributes are not allowed")
        elif not self._is_allowed_attribute(node):
            self._finding(
                node,
                "unknown_attribute",
                "attribute API is not allowlisted",
                symbol=node.attr,
            )
        self.visit(node.value)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if isinstance(node.func, ast.Name) and not self._is_allowed_direct_call(node.func.id):
            if node.func.id not in _FORBIDDEN_NAMES and node.func.id not in _REFLECTION_NAMES:
                self._finding(
                    node.func,
                    "unknown_call",
                    "call target is not allowlisted",
                    symbol=node.func.id,
                )
        if (
            isinstance(node.func, ast.Name)
            and self._aliases.get(node.func.id) == "manim:ImageMobject"
        ):
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant):
                path = first.value
                if not isinstance(path, str) or not _IMAGE_ASSET_PATH.fullmatch(path):
                    self._finding(
                        node,
                        "forbidden_image_path",
                        "ImageMobject path is not allowlisted",
                    )
            elif not isinstance(first, ast.Name | ast.Subscript):
                self._finding(
                    node,
                    "forbidden_image_path",
                    "ImageMobject path is not allowlisted",
                )
        if isinstance(node.func, ast.Attribute) and node.func.attr == "load":
            root = _attribute_root_name(node.func)
            if root is not None and self._aliases.get(root) == "numpy":
                path = (
                    node.args[0].value
                    if node.args and isinstance(node.args[0], ast.Constant)
                    else None
                )
                pickle_kw = next(
                    (
                        keyword.value
                        for keyword in node.keywords
                        if keyword.arg == "allow_pickle"
                    ),
                    None,
                )
                allowed_pickle = (
                    isinstance(pickle_kw, ast.Constant) and pickle_kw.value is False
                )
                if (
                    not isinstance(path, str)
                    or not _ARRAY_ASSET_PATH.fullmatch(path)
                    or not allowed_pickle
                ):
                    self._finding(
                        node,
                        "forbidden_numpy_load",
                        "numpy.load must use an allowlisted array asset with allow_pickle=False",
                    )
        self.visit(node.func)
        for argument in node.args:
            self.visit(argument)
        for keyword in node.keywords:
            if keyword.arg is None:
                self._finding(
                    keyword, "forbidden_keyword_unpacking", "keyword unpacking is not allowed"
                )
            self.visit(keyword.value)

    def visit_Dict(self, node: ast.Dict) -> None:  # noqa: N802
        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                self._finding(
                    node, "forbidden_container_unpacking", "dictionary unpacking is not allowed"
                )
            else:
                self.visit(key)
            self.visit(value)

    def generic_visit(self, node: ast.AST) -> None:
        if not isinstance(node, _ALLOWED_GENERIC_NODES):
            self._finding(
                node,
                "unsupported_syntax",
                "syntax is not allowlisted",
                symbol=type(node).__name__,
            )
            return
        super().generic_visit(node)

    def _declare_target(self, target: ast.expr) -> None:
        if isinstance(target, ast.Name):
            self._declare(target)
            return
        if isinstance(target, ast.List | ast.Tuple):
            for element in target.elts:
                self._declare_target(element)
            return
        if isinstance(target, ast.Starred):
            self._declare_target(target.value)
            return
        if not _is_assignable_target(target):
            self._finding(target, "invalid_assignment", "only local name assignments are allowed")

    def _declare(self, target: ast.Name) -> None:
        if _is_dunder(target.id):
            self._finding(target, "forbidden_dunder", "dunder names are not allowed")
        self._scopes[-1].add(target.id)

    def _is_known_name(self, name: str) -> bool:
        return (
            name in self._aliases
            or name in _SAFE_BUILTINS
            or any(name in scope for scope in self._scopes)
        )

    def _is_allowed_direct_call(self, name: str) -> bool:
        if name in _SAFE_BUILTINS or any(name in scope for scope in self._scopes):
            return True
        alias = self._aliases.get(name)
        return alias is not None and (
            alias.startswith("manim:")
            or alias.startswith("math:")
            or alias.startswith("numpy:")
        )

    def _is_allowed_attribute(self, node: ast.Attribute) -> bool:
        root = _attribute_root_name(node)
        root_alias = self._aliases.get(root) if root is not None else None
        if root_alias == "math":
            return node.attr in _MATH_SYMBOLS
        if root_alias == "numpy":
            return node.attr in _NUMPY_SYMBOLS
        return node.attr in _MANIM_MEMBER_NAMES


def _is_assignable_target(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.List | ast.Tuple):
        return all(_is_assignable_target(element) for element in node.elts)
    if isinstance(node, ast.Starred):
        return _is_assignable_target(node.value)
    return False


def _without_docstring(statements: list[ast.stmt]) -> list[ast.stmt]:
    if statements and isinstance(statements[0], ast.Expr) and isinstance(
        statements[0].value, ast.Constant
    ) and isinstance(statements[0].value.value, str):
        return statements[1:]
    return statements


def _valid_function_signature(node: ast.FunctionDef, *, require_self: bool) -> bool:
    arguments = node.args
    if arguments.vararg is not None or arguments.kwarg is not None or arguments.kwonlyargs:
        return False
    if arguments.defaults or arguments.kw_defaults or arguments.posonlyargs:
        return False
    if require_self:
        return len(arguments.args) == 1 and arguments.args[0].arg == "self"
    return all(not _is_dunder(argument.arg) for argument in arguments.args)


def _is_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str | bytes | int | float | complex | bool | type(None))
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return all(_is_literal(element) for element in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            key is not None and _is_literal(key) and _is_literal(value)
            for key, value in zip(node.keys, node.values, strict=True)
        )
    return False


def _allowed_symbols_for_module(module: str) -> frozenset[str]:
    if module == "manim":
        return _MANIM_SYMBOLS
    if module == "math":
        return _MATH_SYMBOLS
    return _NUMPY_SYMBOLS


def _attribute_root_name(node: ast.Attribute) -> str | None:
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _is_dunder(value: str) -> bool:
    return "__" in value
