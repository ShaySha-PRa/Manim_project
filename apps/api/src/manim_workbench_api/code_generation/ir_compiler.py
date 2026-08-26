"""Deterministic ManimCE 0.21 compiler for Scene IR 1.6. Never emits lambda.

AnimationIR 2.0 lowering lives in ``compiler.manim.compile_animation_ir``.
"""

from __future__ import annotations

import math

from manim_workbench_contracts import CodeModelResponse
from manim_workbench_contracts.ir import (
    BindingSpec,
    CameraOp,
    IrCameraOpKind,
    IrExprId,
    IrObjectType,
    IrStateChangeKind,
    SceneObject,
    SceneStep,
    SceneStoryboard,
    StateChange,
    TrackerSpec,
    VisualKind,
)

from manim_workbench_api.compiler.base import CompiledProgram, CompiledSegment

from .math_expression import (
    MathExpressionError,
    compile_function_expression,
    compile_function_variants,
)

MAX_PLAY_SECONDS = 4.0
ALLOWED_COLORS = {
    "WHITE",
    "BLUE",
    "GREEN",
    "RED",
    "YELLOW",
    "ORANGE",
    "PURPLE",
    "GRAY",
}


class IrCompileError(ValueError):
    """Raised when IR cannot be compiled into allowlisted Manim."""


def compiled_segment_as_response(segment: CompiledSegment) -> CodeModelResponse:
    """Adapt a backend-neutral segment to the teaching provider response contract."""
    return CodeModelResponse(scene_class="GeneratedScene", code=segment.source)


def scene_base_for_step(step: SceneStep) -> str:
    if step.visual_kind is VisualKind.THREE_D:
        return "ThreeDScene"
    if any(
        operation.kind in {IrCameraOpKind.ZOOM_TO, IrCameraOpKind.RESTORE_FRAME}
        for operation in step.camera
    ):
        return "MovingCameraScene"
    return "Scene"


def merge_scene_base(left: str, right: str) -> str | None:
    if left == right:
        return left
    pair = {left, right}
    if pair <= {"Scene", "MovingCameraScene"}:
        return "MovingCameraScene"
    return None


def split_storyboard(storyboard: SceneStoryboard) -> tuple[tuple[SceneStep, ...], ...]:
    groups: list[list[SceneStep]] = []
    current: list[SceneStep] = []
    current_base: str | None = None
    for step in storyboard.steps:
        base = scene_base_for_step(step)
        if not current:
            current = [step]
            current_base = base
            continue
        merged = merge_scene_base(current_base or "Scene", base)
        if merged is None:
            groups.append(current)
            current = [step]
            current_base = base
        else:
            current.append(step)
            current_base = merged
    if current:
        groups.append(current)
    return tuple(tuple(group) for group in groups)


def compile_storyboard(storyboard: SceneStoryboard) -> CompiledProgram:
    groups = split_storyboard(storyboard)
    if not groups:
        raise IrCompileError("storyboard has no steps")
    return CompiledProgram(segments=tuple(_compile_group(group) for group in groups))


def synthesize_storyboard(
    *,
    title: str,
    target_duration_seconds: int,
    category: str,
    expressions: tuple[str, ...],
    explanations: tuple[str, ...],
) -> SceneStoryboard:
    if category == "function_visualization":
        return _function_storyboard(title, target_duration_seconds, expressions, explanations)
    return _formula_storyboard(title, target_duration_seconds, expressions, explanations)


def _formula_storyboard(
    title: str,
    duration: int,
    expressions: tuple[str, ...],
    explanations: tuple[str, ...],
) -> SceneStoryboard:
    steps_text = expressions or (title,)
    equation_type = (
        IrObjectType.TEXT
        if any(ord(character) > 127 for step in steps_text for character in step)
        else IrObjectType.MATH_TEX
    )
    reasons = tuple(
        explanations[index] if index < len(explanations) else "观察等式变化"
        for index in range(len(steps_text))
    )
    objects = (
        SceneObject(id="title", type=IrObjectType.TITLE, text=title, color="YELLOW"),
        SceneObject(
            id="equation",
            type=equation_type,
            text=steps_text[0],
            color="WHITE",
        ),
        SceneObject(
            id="reason",
            type=IrObjectType.TEXT,
            text=reasons[0],
            color="BLUE",
            parent_id="equation",
        ),
    )
    changes: list[StateChange] = [
        StateChange(kind=IrStateChangeKind.WRITE, target_ids=("title",)),
        StateChange(kind=IrStateChangeKind.WRITE, target_ids=("equation", "reason")),
    ]
    for index, expression in enumerate(steps_text[1:], start=1):
        previous = steps_text[index - 1]
        changes.append(
            StateChange(
                kind=IrStateChangeKind.TRANSFORM_MATCHING_TEX,
                target_ids=("equation",),
                from_text=previous,
                to_text=expression,
            )
        )
        changes.append(
            StateChange(
                kind=IrStateChangeKind.TRANSFORM_MATCHING_TEX,
                target_ids=("reason",),
                from_text=reasons[index - 1],
                to_text=reasons[index],
            )
        )
        changes.append(StateChange(kind=IrStateChangeKind.INDICATE, target_ids=("equation",)))
    changes = list(_allocate_active_timeline(changes, duration, ("equation", "reason")))
    return SceneStoryboard(
        target_duration_seconds=duration,
        steps=(
            SceneStep(
                goal=title,
                duration_seconds=float(duration),
                visual_kind=VisualKind.FORMULA,
                objects=objects,
                state_changes=tuple(changes),
            ),
        ),
    )


def _function_storyboard(
    title: str,
    duration: int,
    expressions: tuple[str, ...],
    explanations: tuple[str, ...],
) -> SceneStoryboard:
    compiled_expressions = []
    try:
        for expression in expressions:
            compiled_expressions.extend(compile_function_variants(expression))
    except MathExpressionError as error:
        raise IrCompileError("unsupported function expression") from error
    if not compiled_expressions:
        raise IrCompileError("unsupported function expression")

    objects: list[SceneObject] = [
        SceneObject(id="title", type=IrObjectType.TITLE, text=title, color="YELLOW"),
        SceneObject(id="axes", type=IrObjectType.AXES, color="WHITE"),
        SceneObject(
            id="axis_labels",
            type=IrObjectType.LABEL,
            text="x,y",
            color="WHITE",
            parent_id="axes",
            formula="axes",
        ),
    ]
    changes: list[StateChange] = [
        StateChange(
            kind=IrStateChangeKind.LAGGED_START,
            target_ids=("title", "axes", "axis_labels"),
        )
    ]
    highlight_ids: list[str] = []
    colors = ("BLUE", "YELLOW", "GREEN", "PURPLE")
    for index, compiled in enumerate(compiled_expressions):
        curve_id = f"curve_{index}"
        label_id = f"formula_{index}"
        color = colors[index % len(colors)]
        objects.extend(
            (
                SceneObject(
                    id=curve_id,
                    type=IrObjectType.PLOT,
                    parent_id="axes",
                    formula=compiled.source_expression,
                    color=color,
                ),
                SceneObject(
                    id=label_id,
                    type=IrObjectType.LABEL,
                    text=compiled.source_expression,
                    color=color,
                    x=4.7,
                    y=2.4 - index * 0.55,
                ),
            )
        )
        changes.extend(
            (
                StateChange(kind=IrStateChangeKind.CREATE, target_ids=(curve_id,)),
                StateChange(kind=IrStateChangeKind.FADE_IN, target_ids=(label_id,)),
                StateChange(kind=IrStateChangeKind.INDICATE, target_ids=(curve_id,)),
            )
        )
        highlight_ids.extend((curve_id, label_id))

    plotted_sources = {item.source_expression for item in compiled_expressions}
    extra_formulas = [item for item in expressions if item not in plotted_sources]
    for offset, expression in enumerate(extra_formulas):
        index = len(compiled_expressions) + offset
        label_id = f"formula_{index}"
        explanation = explanations[index] if index < len(explanations) else "关键结论"
        objects.append(
            SceneObject(
                id=label_id,
                type=IrObjectType.LABEL,
                text=expression,
                color="WHITE",
                x=4.7,
                y=2.4 - index * 0.55,
            )
        )
        explanation_id = f"explanation_{index}"
        objects.append(
            SceneObject(
                id=explanation_id,
                type=IrObjectType.LABEL,
                text=explanation,
                color="GRAY",
                x=4.7,
                y=2.12 - index * 0.55,
            )
        )
        changes.append(
            StateChange(
                kind=IrStateChangeKind.FADE_IN,
                target_ids=(label_id, explanation_id),
            )
        )
        highlight_ids.extend((label_id, explanation_id))

    feature_source = next(
        (item for item in reversed(compiled_expressions) if item.quadratic_features()),
        None,
    )
    trackers: tuple[TrackerSpec, ...] = ()
    bindings: tuple[BindingSpec, ...] = ()
    if feature_source is not None:
        features = feature_source.quadratic_features()
        assert features is not None
        vertex_x, vertex_y, roots = features
        objects.extend(
            (
                SceneObject(
                    id="vertex", type=IrObjectType.DOT, x=vertex_x, y=vertex_y, color="RED"
                ),
                SceneObject(
                    id="vertex_label",
                    type=IrObjectType.LABEL,
                    text=f"顶点 ({vertex_x:g}, {vertex_y:g})",
                    color="RED",
                    parent_id="vertex",
                    formula="point",
                ),
                SceneObject(
                    id="symmetry_axis",
                    type=IrObjectType.DASHED_LINE,
                    x=vertex_x,
                    formula="vertical",
                    color="GRAY",
                ),
            )
        )
        changes.extend(
            (
                StateChange(kind=IrStateChangeKind.FADE_IN, target_ids=("vertex",)),
                StateChange(kind=IrStateChangeKind.FADE_IN, target_ids=("vertex_label",)),
                StateChange(kind=IrStateChangeKind.CREATE, target_ids=("symmetry_axis",)),
            )
        )
        highlight_ids.extend(("vertex", "symmetry_axis"))
        for index, root in enumerate(roots):
            root_id = f"root_{index}"
            objects.append(
                SceneObject(id=root_id, type=IrObjectType.DOT, x=root, y=0.0, color="ORANGE")
            )
            changes.append(StateChange(kind=IrStateChangeKind.FADE_IN, target_ids=(root_id,)))
            highlight_ids.append(root_id)
    elif _is_unit_cubic(compiled_expressions[-1].polynomial_coefficients):
        objects.extend(
            (
                SceneObject(id="point", type=IrObjectType.DOT, color="RED"),
                SceneObject(id="tangent", type=IrObjectType.LINE, color="YELLOW"),
                SceneObject(id="readout", type=IrObjectType.LABEL, text="x", color="RED"),
            )
        )
        trackers = (TrackerSpec(id="x", initial=-1.2, minimum=-2.0, maximum=2.0),)
        bindings = (
            BindingSpec(object_id="point", tracker_id="x", expr_id=IrExprId.POW3, role="position"),
            BindingSpec(
                object_id="tangent",
                tracker_id="x",
                expr_id=IrExprId.CUBIC_SLOPE,
                role="tangent",
            ),
            BindingSpec(object_id="readout", tracker_id="x", role="label"),
        )
        changes.extend(
            (
                StateChange(
                    kind=IrStateChangeKind.FADE_IN,
                    target_ids=("point", "tangent", "readout"),
                ),
                StateChange(kind=IrStateChangeKind.SET_VALUE, tracker_id="x", value=1.2),
            )
        )
        highlight_ids.extend(("point", "tangent"))

    changes = list(
        _allocate_active_timeline(
            changes,
            duration,
            tuple(highlight_ids or [f"curve_{len(compiled_expressions) - 1}"]),
        )
    )
    return SceneStoryboard(
        target_duration_seconds=duration,
        steps=(
            SceneStep(
                goal=title,
                duration_seconds=float(duration),
                visual_kind=VisualKind.FUNCTION,
                objects=tuple(objects),
                trackers=trackers,
                bindings=bindings,
                state_changes=tuple(changes),
            ),
        ),
    )


def _allocate_active_timeline(
    changes: list[StateChange], duration: int, highlight_ids: tuple[str, ...]
) -> tuple[StateChange, ...]:
    required_count = max(len(changes), math.ceil(duration / MAX_PLAY_SECONDS))
    if required_count > 48 or not highlight_ids:
        raise IrCompileError("teaching timeline exceeds deterministic limits")
    while len(changes) < required_count:
        target = highlight_ids[(len(changes) - 1) % len(highlight_ids)]
        changes.append(StateChange(kind=IrStateChangeKind.INDICATE, target_ids=(target,)))
    run_time = duration / len(changes)
    if not 0 < run_time <= MAX_PLAY_SECONDS:
        raise IrCompileError("teaching timeline cannot satisfy target duration")
    return tuple(change.model_copy(update={"run_time": run_time}) for change in changes)


def _is_unit_cubic(coefficients: tuple[float, ...] | None) -> bool:
    return coefficients == (0.0, 0.0, 0.0, 1.0)


def _compile_group(steps: tuple[SceneStep, ...]) -> CompiledSegment:
    base = scene_base_for_step(steps[0])
    for step in steps[1:]:
        merged = merge_scene_base(base, scene_base_for_step(step))
        if merged is None:
            raise IrCompileError("incompatible camera bases in one compile group")
        base = merged
    body: list[str] = []
    if base == "MovingCameraScene":
        body.append("        self.camera.frame.save_state()")
    used_math = _uses_math(steps)
    for index, step in enumerate(steps):
        body.extend(_compile_step(step, index, scene_base=base))
    imports = _import_line(steps, base, used_math=used_math)
    source = "\n".join(
        [
            imports,
            "",
            f"class GeneratedScene({base}):",
            "    def construct(self):",
            *body,
            "",
        ]
    )
    kinds = tuple(step.visual_kind for step in steps)
    duration = sum(step.duration_seconds for step in steps)
    return CompiledSegment(
        source=source,
        scene_base=base,
        visual_kinds=kinds,
        duration_seconds=duration,
    )


def _import_line(steps: tuple[SceneStep, ...], base: str, *, used_math: bool) -> str:
    symbols = {
        base,
        "FadeIn",
        "Create",
        "Write",
        "VGroup",
        "Text",
        "MathTex",
        "UP",
        "DOWN",
        "LEFT",
        "RIGHT",
        "WHITE",
        "BLUE",
        "GREEN",
        "RED",
        "YELLOW",
        "Indicate",
        "LaggedStart",
        "AnimationGroup",
        "Succession",
        "TransformMatchingTex",
        "Transform",
        "ValueTracker",
        "always_redraw",
        "DecimalNumber",
        "Dot",
        "Line",
        "DashedLine",
        "Axes",
        "Circle",
        "Polygon",
        "Angle",
        "RightAngle",
        "SurroundingRectangle",
        "Restore",
        "PI",
        "DEGREES",
        "ORIGIN",
        "ORANGE",
        "PURPLE",
        "GRAY",
        "Arrow",
        "NumberPlane",
        "Square",
        "Triangle",
    }
    colors = {obj.color for step in steps for obj in step.objects if obj.color in ALLOWED_COLORS}
    symbols.update(colors)
    if any(step.visual_kind is VisualKind.THREE_D for step in steps):
        symbols.update({"ThreeDAxes", "Surface", "Sphere", "Cube", "OUT", "IN"})
    if any(obj.type is IrObjectType.IMAGE_REF for step in steps for obj in step.objects):
        symbols.add("ImageMobject")
    ordered = ", ".join(sorted(symbols))
    lines = [f"from manim import {ordered}"]
    if used_math:
        lines.append("import math")
    return "\n".join(lines)


def _uses_math(steps: tuple[SceneStep, ...]) -> bool:
    trig = {IrExprId.SINE, IrExprId.SECANT_SLOPE}
    for step in steps:
        if step.visual_kind is VisualKind.FUNCTION:
            return True
        if any(binding.expr_id in trig for binding in step.bindings):
            return True
        for obj in step.objects:
            formula = (obj.formula or "").lower()
            if obj.type is IrObjectType.PLOT and ("sin" in formula or "cos" in formula):
                return True
    return False


def _compile_step(step: SceneStep, index: int, *, scene_base: str) -> list[str]:
    lines = [f"        # step {index + 1}: {step.goal.replace(chr(10), ' ')}"]
    for tracker in step.trackers:
        lines.append(f"        {tracker.id} = ValueTracker({tracker.initial!r})")
    created: dict[str, SceneObject] = {}
    axes_id = next((obj.id for obj in step.objects if obj.type is IrObjectType.AXES), None)
    for obj in _effective_objects(step):
        created[obj.id] = obj
        lines.extend(_emit_object(obj, step.trackers, step.bindings, axes_id=axes_id))
    if step.visual_kind is VisualKind.GEOMETRY_PROOF:
        lines.extend(_emit_proof(step))
    if scene_base == "ThreeDScene":
        lines.extend(_emit_three_d_camera(step))
    for change in step.state_changes:
        lines.extend(_emit_change(change, created))
    for operation in step.camera:
        lines.extend(_emit_camera(operation, scene_base))
    return lines


def _effective_objects(step: SceneStep) -> tuple[SceneObject, ...]:
    extra: list[SceneObject] = []
    for construction in step.constructions:
        extra.append(
            SceneObject(
                id=construction.object_id,
                type=construction.kind,
                text=construction.label,
            )
        )
    return step.objects + tuple(extra)


def _color(obj: SceneObject) -> str:
    color = obj.color if obj.color in ALLOWED_COLORS else "WHITE"
    return color


def _text_literal(value: str) -> str:
    return repr(value)


def _fitted_font_size(text: str, *, default: int, fit_characters: int = 36) -> int:
    """Keep generated single-line teaching text inside the 16:9 safe area."""
    if len(text) <= fit_characters:
        return default
    return max(16, int(default * fit_characters / len(text)))


def _plot_return(formula: str | None) -> str:
    registered = {
        "sin": "y=sin(x)",
        "cos": "y=cos(x)",
        "x^2": "y=x^2",
        "x**2": "y=x**2",
        "x^3": "y=x^3",
        "x**3": "y=x**3",
    }
    expression = registered.get((formula or "").lower().replace(" ", ""), formula or "")
    try:
        compiled = compile_function_expression(expression)
    except MathExpressionError as error:
        raise IrCompileError("unsupported function expression") from error
    if compiled is None:
        raise IrCompileError("unsupported function expression")
    return f"return {compiled.python_expression}"


def _tex_constructor(text: str, *, color: str, font_size: int = 32) -> str:
    if any(ord(character) > 127 for character in text):
        fitted_size = _fitted_font_size(text, default=font_size)
        return (
            f"Text({_text_literal(text)}, font='Noto Sans CJK SC',"
            f" font_size={fitted_size}, color={color})"
        )
    return f"MathTex({_text_literal(text)}, color={color})"


def _emit_object(
    obj: SceneObject,
    trackers: tuple[TrackerSpec, ...],
    bindings: tuple[BindingSpec, ...],
    *,
    axes_id: str | None,
) -> list[str]:
    _ = trackers
    color = _color(obj)
    binding = next((item for item in bindings if item.object_id == obj.id), None)
    if obj.type is IrObjectType.TITLE:
        return [
            f"        {obj.id} = Text({_text_literal(obj.text or '')}, font='Noto Sans CJK SC',"
            f" font_size=36, color={color}).to_edge(UP)"
        ]
    if obj.type is IrObjectType.TEXT:
        suffix = f".next_to({obj.parent_id}, DOWN)" if obj.parent_id else ""
        font_size = _fitted_font_size(obj.text or "", default=28)
        return [
            f"        {obj.id} = Text({_text_literal(obj.text or '')}, font='Noto Sans CJK SC',"
            f" font_size={font_size}, color={color}){suffix}"
        ]
    if obj.type is IrObjectType.MATH_TEX:
        raw = obj.text or ""
        if any(ord(character) > 127 for character in raw):
            font_size = _fitted_font_size(raw, default=32)
            return [
                f"        {obj.id} = Text({_text_literal(raw)}, font='Noto Sans CJK SC',"
                f" font_size={font_size}, color={color}).move_to([0, 0.4, 0])"
            ]
        return [f"        {obj.id} = {_tex_constructor(raw, color=color)}.move_to([0, 0.4, 0])"]
    if obj.type is IrObjectType.EQUATION_PANEL:
        font_size = _fitted_font_size(obj.text or "", default=28)
        return [
            f"        {obj.id}_eq = Text({_text_literal(obj.text or '')}, font='Noto Sans CJK SC',"
            f" font_size={font_size}, color={color})",
            f"        {obj.id}_box = SurroundingRectangle({obj.id}_eq, color={color})",
            f"        {obj.id} = VGroup({obj.id}_box, {obj.id}_eq)",
        ]
    if obj.type is IrObjectType.AXES:
        if (obj.formula or "") == "plane":
            return [f"        {obj.id} = NumberPlane()"]
        return [
            f"        {obj.id} = Axes(x_range=[-3, 3, 1], y_range=[-4, 4, 1],"
            " x_length=8.0, y_length=4.5, tips=False).add_coordinates()"
        ]
    if obj.type is IrObjectType.PLOT:
        parent = obj.parent_id or "axes"
        return [
            f"        def {obj.id}_curve(x):",
            f"            {_plot_return(obj.formula)}",
            f"        {obj.id} = {parent}.plot({obj.id}_curve, x_range=[-3, 3], color={color})",
        ]
    if obj.type is IrObjectType.CIRCLE:
        radius = obj.radius or 1.0
        x_value = obj.x or 0.0
        y_value = obj.y or 0.0
        return [
            f"        {obj.id} = Circle(radius={radius}, color={color}).move_to("
            f"[{x_value}, {y_value}, 0])"
        ]
    if obj.type is IrObjectType.POLYGON:
        points = ", ".join(f"[{x}, {y}, 0]" for x, y in obj.vertices)
        return [f"        {obj.id} = Polygon({points}, color={color})"]
    if obj.type is IrObjectType.ANGLE:
        if binding is not None:
            fn = f"redraw_{obj.id}"
            tracker = binding.tracker_id
            return [
                f"        def {fn}():",
                f"            moving = Line(LEFT, RIGHT).rotate("
                f"{tracker}.get_value() * DEGREES, about_point=LEFT)",
                "            return Angle(Line(LEFT, RIGHT), moving, radius=0.5)",
                f"        {obj.id} = always_redraw({fn})",
            ]
        return [
            f"        {obj.id} = Angle("
            f"Line(LEFT, RIGHT), Line(LEFT, UP), radius=0.5, color={color})"
        ]
    if obj.type is IrObjectType.RIGHT_ANGLE:
        return [
            f"        {obj.id} = RightAngle(Line(LEFT, ORIGIN), Line(ORIGIN, UP),"
            f" length=0.3, color={color})"
        ]
    if obj.type is IrObjectType.DASHED_LINE:
        if obj.formula == "vertical" and axes_id is not None:
            x_value = obj.x or 0.0
            return [
                f"        {obj.id} = DashedLine({axes_id}.c2p({x_value!r}, -4), "
                f"{axes_id}.c2p({x_value!r}, 4), color={color})"
            ]
        return [f"        {obj.id} = DashedLine([-2, 0, 0], [2, 0, 0], color={color})"]
    if obj.type is IrObjectType.GEOMETRY_FIGURE:
        return [
            f"        {obj.id} = VGroup(Polygon([-2, -1, 0], [2, -1, 0], [0, 2, 0], color={color}))"
        ]
    if obj.type is IrObjectType.SPHERE:
        return [f"        {obj.id} = Sphere(radius=1.0, color={color})"]
    if obj.type is IrObjectType.CUBE:
        return [f"        {obj.id} = Cube(side_length=1.5, color={color})"]
    if obj.type is IrObjectType.SURFACE:
        return [
            f"        def {obj.id}_fn(u, v):",
            "            return [u, v, u ** 2 - v ** 2]",
            f"        {obj.id} = Surface({obj.id}_fn, u_range=[-1, 1], v_range=[-1, 1])",
        ]
    if obj.type is IrObjectType.IMAGE_REF:
        assert obj.asset_sha256 is not None
        path = f"/input/assets/{obj.asset_sha256}.png"
        return [f"        {obj.id} = ImageMobject({path!r}).scale(0.8)"]
    if binding is not None:
        return _emit_bound_object(obj, binding, color, axes_id=axes_id)
    if obj.type is IrObjectType.DOT:
        x_value = obj.x or 0.0
        y_value = obj.y or 0.0
        point = (
            f"{axes_id}.c2p({x_value!r}, {y_value!r})"
            if axes_id is not None
            else f"[{x_value}, {y_value}, 0]"
        )
        return [f"        {obj.id} = Dot({point}, color={color})"]
    if obj.type is IrObjectType.LINE:
        if (obj.formula or "") == "arrow":
            x_value = 2.0 if obj.x is None else obj.x
            y_value = 2.0 if obj.y is None else obj.y
            return [
                f"        {obj.id} = Arrow("
                f"ORIGIN, [{x_value}, {y_value}, 0], buff=0, color={color})"
            ]
        x_start = -1.0 if obj.x is None else obj.x
        y_start = 0.0 if obj.y is None else obj.y
        return [f"        {obj.id} = Line([{x_start}, {y_start}, 0], [1, 0, 0], color={color})"]
    if obj.type is IrObjectType.LABEL or obj.type is IrObjectType.DECIMAL:
        if obj.formula == "axes" and obj.parent_id:
            return [
                f"        {obj.id} = {obj.parent_id}.get_axis_labels("
                "Text('x', font='Noto Sans CJK SC', font_size=22), "
                "Text('y', font='Noto Sans CJK SC', font_size=22))"
            ]
        if obj.formula == "point" and obj.parent_id:
            return [
                f"        {obj.id} = Text({_text_literal(obj.text or '')}, "
                f"font='Noto Sans CJK SC', font_size=22, color={color}).next_to("
                f"{obj.parent_id}, UP)"
            ]
        if obj.x is not None or obj.y is not None:
            return [
                f"        {obj.id} = Text({_text_literal(obj.text or '')}, "
                f"font='Noto Sans CJK SC', font_size=22, color={color}).move_to("
                f"[{obj.x or 0.0!r}, {obj.y or 0.0!r}, 0])"
            ]
        return [
            f"        {obj.id} = Text({_text_literal(obj.text or '')}, font='Noto Sans CJK SC',"
            f" font_size=24, color={color}).to_edge(DOWN)"
        ]
    raise IrCompileError(f"unsupported object type: {obj.type.value}")


def _emit_bound_object(
    obj: SceneObject, binding: BindingSpec, color: str, *, axes_id: str | None
) -> list[str]:
    tracker = binding.tracker_id
    fn = f"redraw_{obj.id}"
    expr_x = f"{tracker}.get_value()"
    expr_y = _expr_python(binding.expr_id, tracker)
    if obj.type is IrObjectType.DOT or binding.role == "position":
        point = (
            f"{axes_id}.c2p({expr_x}, {expr_y})"
            if axes_id is not None
            else f"[{expr_x}, {expr_y}, 0]"
        )
        return [
            f"        def {fn}():",
            f"            return Dot({point}, color={color})",
            f"        {obj.id} = always_redraw({fn})",
        ]
    if obj.type is IrObjectType.LINE or binding.role == "tangent":
        return [
            f"        def {fn}():",
            f"            x_value = {tracker}.get_value()",
            f"            slope = {expr_y}",
            "            y_value = x_value ** 3",
            "            return Line(",
            f"                {(axes_id or 'axes')}.c2p(x_value - 0.6, y_value - 0.6 * slope),",
            f"                {(axes_id or 'axes')}.c2p(x_value + 0.6, y_value + 0.6 * slope),",
            f"                color={color},",
            "            )",
            f"        {obj.id} = always_redraw({fn})",
        ]
    return [
        f"        def {fn}():",
        "            return VGroup(",
        f"                Text({_text_literal(obj.text or 'x')}, font='Noto Sans CJK SC',"
        f" font_size=24, color={color}),",
        f"                DecimalNumber("
        f"{tracker}.get_value(), num_decimal_places=2, color={color}),",
        "            ).arrange().to_edge(DOWN)",
        f"        {obj.id} = always_redraw({fn})",
    ]


def _expr_python(expr_id: IrExprId, tracker_id: str) -> str:
    getter = f"{tracker_id}.get_value()"
    mapping = {
        IrExprId.IDENTITY: getter,
        IrExprId.POW2: f"{getter} ** 2",
        IrExprId.POW3: f"{getter} ** 3",
        IrExprId.CUBIC_SLOPE: f"3 * {getter} ** 2",
        IrExprId.SINE: f"math.sin({getter})",
        IrExprId.LINEAR: getter,
        IrExprId.SECANT_SLOPE: f"( ({getter} + 0.4) ** 3 - {getter} ** 3 ) / 0.4",
    }
    return mapping[expr_id]


def _emit_proof(step: SceneStep) -> list[str]:
    lines = [
        "        given_items = VGroup()",
    ]
    for index, item in enumerate(step.given):
        lines.append(
            f"        given_{index} = Text({_text_literal(item)}, font='Noto Sans CJK SC',"
            " font_size=24).to_edge(LEFT)"
        )
        lines.append(f"        given_items.add(given_{index})")
    lines.append("        given_items.arrange(DOWN, buff=0.2).to_edge(LEFT)")
    lines.append(
        f"        prove = Text({_text_literal(step.prove or '')}, font='Noto Sans CJK SC',"
        " font_size=24).to_edge(UP)"
    )
    lines.append(
        "        self.play(LaggedStart(*[FadeIn(item) for item in given_items],"
        " lag_ratio=0.2), run_time=2.0)"
    )
    lines.append("        self.play(Write(prove), run_time=0.8)")
    for index, proof in enumerate(step.proof_steps):
        lines.append(
            f"        proof_{index} = Text({_text_literal(proof.statement + ' — ' + proof.reason)},"
            " font='Noto Sans CJK SC', font_size=22)"
        )
        lines.append(f"        self.play(Write(proof_{index}), run_time=1.2)")
        if proof.object_ids:
            for target in proof.object_ids:
                lines.append(f"        self.play(Indicate({target}), run_time=0.8)")
    return lines


def _emit_three_d_camera(step: SceneStep) -> list[str]:
    orientation = next(
        (op for op in step.camera if op.kind is IrCameraOpKind.SET_ORIENTATION),
        None,
    )
    phi = (
        70.0 if orientation is None or orientation.phi_degrees is None else orientation.phi_degrees
    )
    theta = (
        -45.0
        if orientation is None or orientation.theta_degrees is None
        else orientation.theta_degrees
    )
    lines = [
        f"        self.set_camera_orientation(phi={phi} * DEGREES, theta={theta} * DEGREES)",
        "        axes = ThreeDAxes()",
        "        self.add(axes)",
    ]
    titles = [obj.id for obj in step.objects if obj.type is IrObjectType.TITLE]
    if titles:
        lines.append(f"        self.add_fixed_in_frame_mobjects({titles[0]})")
    return lines


def _emit_change(change: StateChange, created: dict[str, SceneObject]) -> list[str]:
    run_time = min(change.run_time, MAX_PLAY_SECONDS)
    if change.kind is IrStateChangeKind.WAIT:
        return [f"        self.wait({min(change.wait_time, MAX_PLAY_SECONDS)!r})"]
    if change.kind is IrStateChangeKind.SET_VALUE:
        if change.tracker_id is None or change.value is None:
            raise IrCompileError("set_value requires tracker_id and value")
        return [
            f"        self.play({change.tracker_id}.animate.set_value({change.value!r}),"
            f" run_time={run_time!r})"
        ]
    if change.kind is IrStateChangeKind.TRANSFORM_MATCHING_TEX:
        if not change.target_ids or change.to_text is None:
            raise IrCompileError("transform_matching_tex requires target and to_text")
        target = change.target_ids[0]
        target_object = created.get(target)
        use_text = target_object is not None and target_object.type is IrObjectType.TEXT
        fitted_size = _fitted_font_size(change.to_text, default=28)
        next_mobject = (
            f"Text({_text_literal(change.to_text)}, font='Noto Sans CJK SC', "
            f"font_size={fitted_size}, color=BLUE)"
            if use_text
            else _tex_constructor(change.to_text, color="WHITE")
        )
        transform = (
            "Transform"
            if use_text or any(ord(character) > 127 for character in change.to_text)
            else "TransformMatchingTex"
        )
        return [
            f"        {target}_next = {next_mobject}",
            f"        {target}_next.move_to({target}.get_center())",
            f"        self.play({transform}({target}, {target}_next), run_time={run_time!r})",
        ]
    if change.kind is IrStateChangeKind.INDICATE:
        if not change.target_ids:
            raise IrCompileError("indicate requires target_ids")
        animations = ", ".join(
            f"Indicate({target}, scale_factor=1.05)" for target in change.target_ids
        )
        return [f"        self.play({animations}, run_time={run_time!r})"]
    if change.kind in {
        IrStateChangeKind.WRITE,
        IrStateChangeKind.CREATE,
        IrStateChangeKind.FADE_IN,
        IrStateChangeKind.LAGGED_START,
        IrStateChangeKind.ANIMATION_GROUP,
        IrStateChangeKind.SUCCESSION,
    }:
        factory = {
            IrStateChangeKind.WRITE: "Write",
            IrStateChangeKind.CREATE: "Create",
            IrStateChangeKind.FADE_IN: "FadeIn",
        }
        animations = []
        for target in change.target_ids:
            ctor = factory.get(change.kind, "FadeIn")
            animations.append(f"{ctor}({target})")
        if not animations:
            return []
        joined = ", ".join(animations)
        if change.kind is IrStateChangeKind.LAGGED_START:
            return [
                f"        self.play(LaggedStart({joined}, lag_ratio={change.lag_ratio!r}),"
                f" run_time={run_time!r})"
            ]
        if change.kind is IrStateChangeKind.SUCCESSION:
            return [f"        self.play(Succession({joined}), run_time={run_time!r})"]
        if change.kind is IrStateChangeKind.ANIMATION_GROUP:
            return [f"        self.play(AnimationGroup({joined}), run_time={run_time!r})"]
        return [f"        self.play({joined}, run_time={run_time!r})"]
    raise IrCompileError(f"unsupported state change: {change.kind.value}")


def _emit_camera(operation: CameraOp, scene_base: str) -> list[str]:
    run_time = min(operation.run_time, MAX_PLAY_SECONDS)
    if operation.kind is IrCameraOpKind.ZOOM_TO:
        if scene_base != "MovingCameraScene" or operation.object_id is None:
            raise IrCompileError("zoom_to requires MovingCameraScene and object_id")
        scale = operation.scale or 0.45
        return [
            f"        self.play(self.camera.frame.animate.scale({scale!r}).move_to("
            f"{operation.object_id}), run_time={run_time!r})"
        ]
    if operation.kind is IrCameraOpKind.RESTORE_FRAME:
        return [f"        self.play(Restore(self.camera.frame), run_time={run_time!r})"]
    if operation.kind is IrCameraOpKind.SET_ORIENTATION:
        return []
    if operation.kind is IrCameraOpKind.AMBIENT_ROTATE:
        rate = operation.rate or 0.15
        return [
            f"        self.begin_ambient_camera_rotation(rate={rate!r})",
            f"        self.wait({run_time!r})",
        ]
    raise IrCompileError(f"unsupported camera op: {operation.kind.value}")
