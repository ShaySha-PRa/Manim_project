"""Deterministic ManimCE 0.21 compiler for Scene IR. Never emits lambda."""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class CompiledSegment:
    source: str
    scene_base: str
    visual_kinds: tuple[VisualKind, ...]
    duration_seconds: float

    def as_response(self) -> CodeModelResponse:
        return CodeModelResponse(scene_class="GeneratedScene", code=self.source)


@dataclass(frozen=True, slots=True)
class CompiledProgram:
    segments: tuple[CompiledSegment, ...]

    @property
    def requires_concat(self) -> bool:
        return len(self.segments) > 1


class IrCompileError(ValueError):
    """Raised when IR cannot be compiled into allowlisted Manim."""


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
        return _function_storyboard(title, target_duration_seconds, expressions)
    return _formula_storyboard(title, target_duration_seconds, expressions, explanations)


def _formula_storyboard(
    title: str,
    duration: int,
    expressions: tuple[str, ...],
    explanations: tuple[str, ...],
) -> SceneStoryboard:
    steps_text = expressions or (title,)
    objects = (
        SceneObject(id="title", type=IrObjectType.TITLE, text=title, color="YELLOW"),
        SceneObject(
            id="equation",
            type=IrObjectType.MATH_TEX,
            text=steps_text[0],
            color="WHITE",
        ),
    )
    changes: list[StateChange] = [
        StateChange(kind=IrStateChangeKind.WRITE, target_ids=("title",), run_time=0.8),
        StateChange(kind=IrStateChangeKind.WRITE, target_ids=("equation",), run_time=1.0),
    ]
    for index, expression in enumerate(steps_text[1:], start=1):
        previous = steps_text[index - 1]
        changes.append(
            StateChange(
                kind=IrStateChangeKind.TRANSFORM_MATCHING_TEX,
                target_ids=("equation",),
                from_text=previous,
                to_text=expression,
                run_time=min(2.0, MAX_PLAY_SECONDS),
            )
        )
    changes.append(StateChange(kind=IrStateChangeKind.WAIT, wait_time=0.6, run_time=0.6))
    _ = explanations
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
    title: str, duration: int, expressions: tuple[str, ...]
) -> SceneStoryboard:
    formula = expressions[0] if expressions else "y=x^3"
    return SceneStoryboard(
        target_duration_seconds=duration,
        steps=(
            SceneStep(
                goal=title,
                duration_seconds=float(duration),
                visual_kind=VisualKind.FUNCTION,
                objects=(
                    SceneObject(id="title", type=IrObjectType.TITLE, text=title, color="YELLOW"),
                    SceneObject(id="axes", type=IrObjectType.AXES, color="WHITE"),
                    SceneObject(
                        id="curve",
                        type=IrObjectType.PLOT,
                        parent_id="axes",
                        formula=formula,
                        color="BLUE",
                    ),
                    SceneObject(id="point", type=IrObjectType.DOT, color="RED"),
                    SceneObject(id="tangent", type=IrObjectType.LINE, color="YELLOW"),
                    SceneObject(id="readout", type=IrObjectType.LABEL, text="x", color="RED"),
                ),
                trackers=(TrackerSpec(id="x", initial=-1.2, minimum=-2.0, maximum=2.0),),
                bindings=(
                    BindingSpec(
                        object_id="point", tracker_id="x", expr_id=IrExprId.POW3, role="position"
                    ),
                    BindingSpec(
                        object_id="tangent",
                        tracker_id="x",
                        expr_id=IrExprId.CUBIC_SLOPE,
                        role="tangent",
                    ),
                    BindingSpec(
                        object_id="readout", tracker_id="x", expr_id=IrExprId.IDENTITY, role="label"
                    ),
                ),
                state_changes=(
                    StateChange(
                        kind=IrStateChangeKind.LAGGED_START,
                        target_ids=("title", "axes", "curve"),
                        run_time=2.0,
                    ),
                    StateChange(
                        kind=IrStateChangeKind.FADE_IN,
                        target_ids=("point", "tangent", "readout"),
                        run_time=0.8,
                    ),
                    StateChange(
                        kind=IrStateChangeKind.SET_VALUE, tracker_id="x", value=1.2, run_time=3.0
                    ),
                    StateChange(kind=IrStateChangeKind.WAIT, wait_time=0.5, run_time=0.5),
                ),
            ),
        ),
    )


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
    colors = {
        obj.color
        for step in steps
        for obj in step.objects
        if obj.color in ALLOWED_COLORS
    }
    symbols.update(colors)
    if any(step.visual_kind is VisualKind.THREE_D for step in steps):
        symbols.update(
            {"ThreeDAxes", "Surface", "Sphere", "Cube", "OUT", "IN"}
        )
    if any(
        obj.type is IrObjectType.IMAGE_REF for step in steps for obj in step.objects
    ):
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
    has_axes = any(obj.type is IrObjectType.AXES for obj in step.objects)
    for obj in _effective_objects(step):
        created[obj.id] = obj
        lines.extend(_emit_object(obj, step.trackers, step.bindings, has_axes=has_axes))
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


def _plot_return(formula: str | None) -> str:
    text = (formula or "").lower().replace(" ", "")
    if "sin" in text:
        return "return math.sin(x)"
    if "cos" in text:
        return "return math.cos(x)"
    if "x^2" in text or "x**2" in text:
        return "return x ** 2"
    return "return x ** 3"


def _tex_constructor(text: str, *, color: str, font_size: int = 32) -> str:
    if any(ord(character) > 127 for character in text):
        return (
            f"Text({_text_literal(text)}, font='Noto Sans CJK SC',"
            f" font_size={font_size}, color={color})"
        )
    return f"MathTex({_text_literal(text)}, color={color})"


def _emit_object(
    obj: SceneObject,
    trackers: tuple[TrackerSpec, ...],
    bindings: tuple[BindingSpec, ...],
    *,
    has_axes: bool,
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
        return [
            f"        {obj.id} = Text({_text_literal(obj.text or '')}, font='Noto Sans CJK SC',"
            f" font_size=28, color={color})"
        ]
    if obj.type is IrObjectType.MATH_TEX:
        raw = obj.text or ""
        if any(ord(character) > 127 for character in raw):
            return [
                f"        {obj.id} = Text({_text_literal(raw)}, font='Noto Sans CJK SC',"
                f" font_size=32, color={color})"
            ]
        return [f"        {obj.id} = {_tex_constructor(raw, color=color)}"]
    if obj.type is IrObjectType.EQUATION_PANEL:
        return [
            f"        {obj.id}_eq = Text({_text_literal(obj.text or '')}, font='Noto Sans CJK SC',"
            f" font_size=28, color={color})",
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
        return [
            f"        {obj.id} = DashedLine([-2, 0, 0], [2, 0, 0], color={color})"
        ]
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
        return _emit_bound_object(obj, binding, color, has_axes=has_axes)
    if obj.type is IrObjectType.DOT:
        x_value = obj.x or 0.0
        y_value = obj.y or 0.0
        return [f"        {obj.id} = Dot([{x_value}, {y_value}, 0], color={color})"]
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
        return [
            f"        {obj.id} = Line([{x_start}, {y_start}, 0], [1, 0, 0], color={color})"
        ]
    if obj.type is IrObjectType.LABEL or obj.type is IrObjectType.DECIMAL:
        return [
            f"        {obj.id} = Text({_text_literal(obj.text or '')}, font='Noto Sans CJK SC',"
            f" font_size=24, color={color}).to_edge(DOWN)"
        ]
    raise IrCompileError(f"unsupported object type: {obj.type.value}")


def _emit_bound_object(
    obj: SceneObject, binding: BindingSpec, color: str, *, has_axes: bool
) -> list[str]:
    tracker = binding.tracker_id
    fn = f"redraw_{obj.id}"
    expr_x = f"{tracker}.get_value()"
    expr_y = _expr_python(binding.expr_id, tracker)
    if obj.type is IrObjectType.DOT or binding.role == "position":
        point = (
            f"axes.c2p({expr_x}, {expr_y})"
            if has_axes
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
            "                axes.c2p(x_value - 0.6, y_value - 0.6 * slope),",
            "                axes.c2p(x_value + 0.6, y_value + 0.6 * slope),",
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
        70.0
        if orientation is None or orientation.phi_degrees is None
        else orientation.phi_degrees
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
    _ = created
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
        next_mobject = _tex_constructor(change.to_text, color="WHITE")
        return [
            f"        {target}_next = {next_mobject}",
            f"        self.play(TransformMatchingTex({target}, {target}_next),"
            f" run_time={run_time!r})",
            f"        {target} = {target}_next",
        ]
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
            return [
                f"        self.play(Succession({joined}), run_time={run_time!r})"
            ]
        if change.kind is IrStateChangeKind.ANIMATION_GROUP:
            return [
                f"        self.play(AnimationGroup({joined}), run_time={run_time!r})"
            ]
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
