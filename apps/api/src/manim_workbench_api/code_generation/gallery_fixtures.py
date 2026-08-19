"""Scene IR fixtures adapted from the Manim Community Example Gallery.

Source: https://docs.manim.community/en/stable/examples.html (ManimCE 0.21.0)

Official snippets often use lambda / add_updater / ZoomedScene / numpy ImageMobject.
These IR versions keep the teaching intent and compile to named always_redraw
functions that pass the workbench allowlist.
"""

from manim_workbench_contracts.ir import (
    BindingSpec,
    CameraOp,
    IrCameraOpKind,
    IrExprId,
    IrObjectType,
    IrStateChangeKind,
    ProofStep,
    SceneObject,
    SceneStep,
    SceneStoryboard,
    StateChange,
    TrackerSpec,
    VisualKind,
)

GALLERY_SOURCE = "https://docs.manim.community/en/stable/examples.html"

# Official gallery class names that are not compiled as IR gold.
SKIPPED_OFFICIAL_EXAMPLES = {
    "ManimCELogo": "hex colors and camera.background_color are outside the allowlist",
    "GradientImageFromArray": "numpy ImageMobject arrays are not an uploaded asset path",
    "BooleanOperations": "boolean ops, MarkupText, and Group are not allowlisted",
    "RotationUpdater": "add_updater is forbidden; use named always_redraw instead",
    "PointWithTrace": "TracedPath is not allowlisted",
    "HeatDiagramPlot": "custom axis numbering is out of the current IR surface",
    "MovingZoomedSceneAround": "ZoomedScene is not an allowed Scene base",
    "ThreeDLightSourcePosition": "lights and parametric surfaces beyond Sphere/Surface IR",
    "ThreeDCameraIllusionRotation": "covered by ThreeDCameraRotation",
}


def brace_annotation_storyboard() -> SceneStoryboard:
    """Gallery: BraceAnnotation — annotate a segment between two points."""
    return SceneStoryboard(
        target_duration_seconds=16,
        steps=(
            SceneStep(
                goal="Label the distance between two points",
                duration_seconds=16,
                visual_kind=VisualKind.PLANE_GEOMETRY,
                objects=(
                    SceneObject(id="dot_a", type=IrObjectType.DOT, x=-2.0, y=-1.0, color="WHITE"),
                    SceneObject(id="dot_b", type=IrObjectType.DOT, x=2.0, y=1.0, color="WHITE"),
                    SceneObject(id="segment", type=IrObjectType.LINE, color="ORANGE"),
                    SceneObject(
                        id="label",
                        type=IrObjectType.LABEL,
                        text="x-x_1",
                        color="YELLOW",
                    ),
                ),
                state_changes=(
                    StateChange(
                        kind=IrStateChangeKind.CREATE,
                        target_ids=("dot_a", "dot_b", "segment"),
                        run_time=1.5,
                    ),
                    StateChange(
                        kind=IrStateChangeKind.WRITE, target_ids=("label",), run_time=1.0
                    ),
                ),
            ),
        ),
    )


def vector_arrow_storyboard() -> SceneStoryboard:
    """Gallery: VectorArrow — origin, arrow, and coordinate labels."""
    return SceneStoryboard(
        target_duration_seconds=16,
        steps=(
            SceneStep(
                goal="Show a vector from the origin to (2, 2)",
                duration_seconds=16,
                visual_kind=VisualKind.PLANE_GEOMETRY,
                objects=(
                    SceneObject(id="plane", type=IrObjectType.AXES, formula="plane"),
                    SceneObject(
                        id="origin_dot",
                        type=IrObjectType.DOT,
                        x=0.0,
                        y=0.0,
                        color="WHITE",
                    ),
                    SceneObject(
                        id="arrow",
                        type=IrObjectType.LINE,
                        formula="arrow",
                        x=2.0,
                        y=2.0,
                        color="YELLOW",
                    ),
                    SceneObject(
                        id="origin_text",
                        type=IrObjectType.TEXT,
                        text="(0, 0)",
                        color="WHITE",
                    ),
                    SceneObject(
                        id="tip_text",
                        type=IrObjectType.TEXT,
                        text="(2, 2)",
                        color="WHITE",
                    ),
                ),
                state_changes=(
                    StateChange(
                        kind=IrStateChangeKind.FADE_IN,
                        target_ids=("plane", "origin_dot", "arrow", "origin_text", "tip_text"),
                        run_time=2.0,
                    ),
                ),
            ),
        ),
    )


def point_moving_on_shapes_storyboard() -> SceneStoryboard:
    """Gallery: PointMovingOnShapes — a dot travels around a circle."""
    return SceneStoryboard(
        target_duration_seconds=16,
        steps=(
            SceneStep(
                goal="Move a point around a circle",
                duration_seconds=16,
                visual_kind=VisualKind.PLANE_GEOMETRY,
                objects=(
                    SceneObject(id="circle", type=IrObjectType.CIRCLE, radius=1.0, color="BLUE"),
                    SceneObject(id="dot", type=IrObjectType.DOT, color="WHITE"),
                    SceneObject(id="guide", type=IrObjectType.LINE, color="WHITE"),
                ),
                trackers=(TrackerSpec(id="theta", initial=0.0, minimum=0.0, maximum=3.0),),
                bindings=(
                    BindingSpec(
                        object_id="dot",
                        tracker_id="theta",
                        expr_id=IrExprId.SINE,
                        role="position",
                    ),
                ),
                state_changes=(
                    StateChange(
                        kind=IrStateChangeKind.CREATE,
                        target_ids=("circle", "guide"),
                        run_time=1.2,
                    ),
                    StateChange(
                        kind=IrStateChangeKind.SET_VALUE,
                        tracker_id="theta",
                        value=3.0,
                        run_time=3.0,
                    ),
                ),
            ),
        ),
    )


def moving_around_storyboard() -> SceneStoryboard:
    """Gallery: MovingAround — create then emphasize a square."""
    return SceneStoryboard(
        target_duration_seconds=16,
        steps=(
            SceneStep(
                goal="Create a square and indicate it",
                duration_seconds=16,
                visual_kind=VisualKind.PLANE_GEOMETRY,
                objects=(
                    SceneObject(
                        id="square",
                        type=IrObjectType.POLYGON,
                        vertices=((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)),
                        color="BLUE",
                    ),
                ),
                state_changes=(
                    StateChange(
                        kind=IrStateChangeKind.CREATE,
                        target_ids=("square",),
                        run_time=1.5,
                    ),
                    StateChange(kind=IrStateChangeKind.WAIT, wait_time=0.8, run_time=0.8),
                ),
            ),
        ),
    )


def moving_angle_storyboard() -> SceneStoryboard:
    """Gallery: MovingAngle — ValueTracker drives an angle."""
    return SceneStoryboard(
        target_duration_seconds=16,
        steps=(
            SceneStep(
                goal="Rotate an angle with a ValueTracker",
                duration_seconds=16,
                visual_kind=VisualKind.PLANE_GEOMETRY,
                objects=(
                    SceneObject(id="line_fixed", type=IrObjectType.LINE, color="WHITE"),
                    SceneObject(id="line_moving", type=IrObjectType.LINE, color="BLUE"),
                    SceneObject(id="angle_mark", type=IrObjectType.ANGLE, color="YELLOW"),
                    SceneObject(id="theta", type=IrObjectType.MATH_TEX, text=r"\theta"),
                ),
                trackers=(TrackerSpec(id="theta_tracker", initial=110, minimum=0, maximum=350),),
                bindings=(
                    BindingSpec(
                        object_id="angle_mark",
                        tracker_id="theta_tracker",
                        expr_id=IrExprId.IDENTITY,
                        role="label",
                    ),
                ),
                state_changes=(
                    StateChange(
                        kind=IrStateChangeKind.CREATE,
                        target_ids=("line_fixed", "line_moving", "angle_mark"),
                        run_time=1.0,
                    ),
                    StateChange(
                        kind=IrStateChangeKind.SET_VALUE,
                        tracker_id="theta_tracker",
                        value=40,
                        run_time=2.0,
                    ),
                    StateChange(
                        kind=IrStateChangeKind.SET_VALUE,
                        tracker_id="theta_tracker",
                        value=180,
                        run_time=2.0,
                    ),
                ),
            ),
        ),
    )


def moving_dots_storyboard() -> SceneStoryboard:
    """Gallery: MovingDots — two tracker-driven points."""
    return SceneStoryboard(
        target_duration_seconds=16,
        steps=(
            SceneStep(
                goal="Move two dots with a shared ValueTracker",
                duration_seconds=16,
                visual_kind=VisualKind.FUNCTION,
                objects=(
                    SceneObject(id="axes", type=IrObjectType.AXES),
                    SceneObject(id="dot_a", type=IrObjectType.DOT, color="RED"),
                    SceneObject(id="dot_b", type=IrObjectType.DOT, color="BLUE"),
                ),
                trackers=(TrackerSpec(id="t", initial=-1.0, minimum=-2.0, maximum=2.0),),
                bindings=(
                    BindingSpec(
                        object_id="dot_a",
                        tracker_id="t",
                        expr_id=IrExprId.LINEAR,
                        role="position",
                    ),
                    BindingSpec(
                        object_id="dot_b",
                        tracker_id="t",
                        expr_id=IrExprId.POW2,
                        role="position",
                    ),
                ),
                state_changes=(
                    StateChange(kind=IrStateChangeKind.CREATE, target_ids=("axes",), run_time=1.0),
                    StateChange(
                        kind=IrStateChangeKind.SET_VALUE, tracker_id="t", value=1.5, run_time=3.0
                    ),
                ),
            ),
        ),
    )


def moving_frame_box_storyboard() -> SceneStoryboard:
    """Gallery: MovingFrameBox — highlight and transform a formula."""
    return SceneStoryboard(
        target_duration_seconds=16,
        steps=(
            SceneStep(
                goal="Box a formula then transform matching TeX",
                duration_seconds=16,
                visual_kind=VisualKind.FORMULA,
                objects=(
                    SceneObject(
                        id="panel",
                        type=IrObjectType.EQUATION_PANEL,
                        text=r"a^2 + b^2",
                        color="YELLOW",
                    ),
                    SceneObject(
                        id="equation",
                        type=IrObjectType.MATH_TEX,
                        text=r"a^2 + b^2",
                    ),
                ),
                state_changes=(
                    StateChange(
                        kind=IrStateChangeKind.WRITE,
                        target_ids=("panel", "equation"),
                        run_time=1.5,
                    ),
                    StateChange(
                        kind=IrStateChangeKind.TRANSFORM_MATCHING_TEX,
                        target_ids=("equation",),
                        from_text=r"a^2 + b^2",
                        to_text=r"c^2",
                        run_time=2.0,
                    ),
                ),
            ),
        ),
    )


def following_graph_camera_storyboard() -> SceneStoryboard:
    """Gallery: FollowingGraphCamera — zoom to a moving point then restore."""
    return SceneStoryboard(
        target_duration_seconds=16,
        steps=(
            SceneStep(
                goal="Follow a point on a sine graph then restore the frame",
                duration_seconds=16,
                visual_kind=VisualKind.FUNCTION,
                objects=(
                    SceneObject(id="title", type=IrObjectType.TITLE, text="y = sin x"),
                    SceneObject(id="axes", type=IrObjectType.AXES),
                    SceneObject(
                        id="curve",
                        type=IrObjectType.PLOT,
                        parent_id="axes",
                        formula="sin",
                        color="BLUE",
                    ),
                    SceneObject(id="point", type=IrObjectType.DOT, color="ORANGE"),
                ),
                trackers=(TrackerSpec(id="x", initial=0.0, minimum=0.0, maximum=3.0),),
                bindings=(
                    BindingSpec(
                        object_id="point",
                        tracker_id="x",
                        expr_id=IrExprId.SINE,
                        role="position",
                    ),
                ),
                state_changes=(
                    StateChange(
                        kind=IrStateChangeKind.LAGGED_START,
                        target_ids=("title", "axes", "curve", "point"),
                        run_time=2.0,
                    ),
                    StateChange(
                        kind=IrStateChangeKind.SET_VALUE,
                        tracker_id="x",
                        value=3.0,
                        run_time=3.0,
                    ),
                ),
                camera=(
                    CameraOp(
                        kind=IrCameraOpKind.ZOOM_TO,
                        object_id="point",
                        scale=0.5,
                        run_time=1.5,
                    ),
                    CameraOp(kind=IrCameraOpKind.RESTORE_FRAME, run_time=1.5),
                ),
            ),
        ),
    )


def fixed_in_frame_storyboard() -> SceneStoryboard:
    """Gallery: FixedInFrameMObjectTest — 3D axes with a fixed HUD title."""
    return SceneStoryboard(
        target_duration_seconds=16,
        steps=(
            SceneStep(
                goal="Keep a title fixed while the 3D camera is oriented",
                duration_seconds=16,
                visual_kind=VisualKind.THREE_D,
                objects=(
                    SceneObject(id="title", type=IrObjectType.TITLE, text="This is a 3D text"),
                    SceneObject(id="sphere", type=IrObjectType.SPHERE, color="RED"),
                ),
                camera=(
                    CameraOp(
                        kind=IrCameraOpKind.SET_ORIENTATION,
                        phi_degrees=75,
                        theta_degrees=-45,
                    ),
                    CameraOp(kind=IrCameraOpKind.AMBIENT_ROTATE, rate=0.15, run_time=3.0),
                ),
            ),
        ),
    )


def polygon_on_axes_storyboard() -> SceneStoryboard:
    """Gallery: PolygonOnAxes — polygon region on Axes."""
    return SceneStoryboard(
        target_duration_seconds=16,
        steps=(
            SceneStep(
                goal="Grow a polygon under a curve",
                duration_seconds=16,
                visual_kind=VisualKind.PLANE_GEOMETRY,
                objects=(
                    SceneObject(id="axes", type=IrObjectType.AXES),
                    SceneObject(
                        id="region",
                        type=IrObjectType.POLYGON,
                        vertices=((-2.0, 0.0), (2.0, 0.0), (0.0, 2.0)),
                        color="BLUE",
                    ),
                    SceneObject(id="label", type=IrObjectType.LABEL, text="area", color="YELLOW"),
                ),
                constructions=(),
                state_changes=(
                    StateChange(kind=IrStateChangeKind.CREATE, target_ids=("axes",), run_time=1.0),
                    StateChange(
                        kind=IrStateChangeKind.FADE_IN, target_ids=("region", "label"), run_time=1.2
                    ),
                ),
            ),
        ),
    )


def opening_manim_formula_storyboard() -> SceneStoryboard:
    """Gallery: OpeningManim — formula written then transformed."""
    return SceneStoryboard(
        target_duration_seconds=16,
        steps=(
            SceneStep(
                goal="Write the Basel problem then transform the result",
                duration_seconds=16,
                visual_kind=VisualKind.FORMULA,
                objects=(
                    SceneObject(id="title", type=IrObjectType.TITLE, text="Opening Manim"),
                    SceneObject(
                        id="equation",
                        type=IrObjectType.MATH_TEX,
                        text=r"\sum_{n=1}^\infty \frac{1}{n^2}",
                    ),
                ),
                state_changes=(
                    StateChange(kind=IrStateChangeKind.WRITE, target_ids=("title",), run_time=0.8),
                    StateChange(
                        kind=IrStateChangeKind.WRITE, target_ids=("equation",), run_time=1.2
                    ),
                    StateChange(
                        kind=IrStateChangeKind.TRANSFORM_MATCHING_TEX,
                        target_ids=("equation",),
                        from_text=r"\sum_{n=1}^\infty \frac{1}{n^2}",
                        to_text=r"\frac{\pi^2}{6}",
                        run_time=2.0,
                    ),
                ),
            ),
        ),
    )


def sin_and_cos_function_plot_storyboard() -> SceneStoryboard:
    """Gallery: SinAndCosFunctionPlot — two named plots on Axes."""
    return SceneStoryboard(
        target_duration_seconds=16,
        steps=(
            SceneStep(
                goal="Plot sine and cosine on the same axes",
                duration_seconds=16,
                visual_kind=VisualKind.FUNCTION,
                objects=(
                    SceneObject(id="axes", type=IrObjectType.AXES),
                    SceneObject(
                        id="sine",
                        type=IrObjectType.PLOT,
                        parent_id="axes",
                        formula="sin",
                        color="BLUE",
                    ),
                    SceneObject(
                        id="cosine",
                        type=IrObjectType.PLOT,
                        parent_id="axes",
                        formula="cos",
                        color="RED",
                    ),
                ),
                state_changes=(
                    StateChange(
                        kind=IrStateChangeKind.LAGGED_START,
                        target_ids=("axes", "sine", "cosine"),
                        run_time=2.0,
                    ),
                ),
            ),
        ),
    )


def arg_min_example_storyboard() -> SceneStoryboard:
    """Gallery: ArgMinExample — tracker walks a parabola toward a minimum."""
    return SceneStoryboard(
        target_duration_seconds=16,
        steps=(
            SceneStep(
                goal="Move a point toward the minimum of a parabola",
                duration_seconds=16,
                visual_kind=VisualKind.FUNCTION,
                objects=(
                    SceneObject(id="axes", type=IrObjectType.AXES),
                    SceneObject(
                        id="curve",
                        type=IrObjectType.PLOT,
                        parent_id="axes",
                        formula="x^2",
                        color="BLUE",
                    ),
                    SceneObject(id="point", type=IrObjectType.DOT, color="YELLOW"),
                ),
                trackers=(TrackerSpec(id="x", initial=-1.5, minimum=-2.0, maximum=2.0),),
                bindings=(
                    BindingSpec(
                        object_id="point",
                        tracker_id="x",
                        expr_id=IrExprId.POW2,
                        role="position",
                    ),
                ),
                state_changes=(
                    StateChange(
                        kind=IrStateChangeKind.CREATE,
                        target_ids=("axes", "curve", "point"),
                        run_time=1.5,
                    ),
                    StateChange(
                        kind=IrStateChangeKind.SET_VALUE, tracker_id="x", value=0.0, run_time=3.0
                    ),
                ),
            ),
        ),
    )


def graph_area_plot_storyboard() -> SceneStoryboard:
    """Gallery: GraphAreaPlot — curve plus a polygonal area."""
    return SceneStoryboard(
        target_duration_seconds=16,
        steps=(
            SceneStep(
                goal="Show the area under a curve as a polygon",
                duration_seconds=16,
                visual_kind=VisualKind.FUNCTION,
                objects=(
                    SceneObject(id="axes", type=IrObjectType.AXES),
                    SceneObject(
                        id="curve",
                        type=IrObjectType.PLOT,
                        parent_id="axes",
                        formula="sin",
                        color="BLUE",
                    ),
                    SceneObject(
                        id="area",
                        type=IrObjectType.POLYGON,
                        vertices=((-2.0, 0.0), (-1.0, 0.8), (1.0, 0.8), (2.0, 0.0)),
                        color="GREEN",
                    ),
                ),
                state_changes=(
                    StateChange(
                        kind=IrStateChangeKind.CREATE, target_ids=("axes", "curve"), run_time=1.5
                    ),
                    StateChange(kind=IrStateChangeKind.FADE_IN, target_ids=("area",), run_time=1.2),
                ),
            ),
        ),
    )


def three_d_camera_rotation_storyboard() -> SceneStoryboard:
    """Gallery: ThreeDCameraRotation — ambient camera around a sphere."""
    return SceneStoryboard(
        target_duration_seconds=16,
        steps=(
            SceneStep(
                goal="Rotate the 3D camera around a sphere",
                duration_seconds=16,
                visual_kind=VisualKind.THREE_D,
                objects=(SceneObject(id="sphere", type=IrObjectType.SPHERE, color="BLUE"),),
                camera=(
                    CameraOp(
                        kind=IrCameraOpKind.SET_ORIENTATION,
                        phi_degrees=70,
                        theta_degrees=30,
                    ),
                    CameraOp(kind=IrCameraOpKind.AMBIENT_ROTATE, rate=0.2, run_time=3.0),
                ),
            ),
        ),
    )


def three_d_surface_plot_storyboard() -> SceneStoryboard:
    """Gallery: ThreeDSurfacePlot — named Surface function, no lambda."""
    return SceneStoryboard(
        target_duration_seconds=16,
        steps=(
            SceneStep(
                goal="Plot a 3D saddle surface",
                duration_seconds=16,
                visual_kind=VisualKind.THREE_D,
                objects=(SceneObject(id="saddle", type=IrObjectType.SURFACE, color="BLUE"),),
                camera=(
                    CameraOp(
                        kind=IrCameraOpKind.SET_ORIENTATION,
                        phi_degrees=75,
                        theta_degrees=-45,
                    ),
                    CameraOp(kind=IrCameraOpKind.AMBIENT_ROTATE, rate=0.1, run_time=3.0),
                ),
            ),
        ),
    )


def sine_curve_unit_circle_storyboard() -> SceneStoryboard:
    """Gallery: SineCurveUnitCircle — unit circle plus a sine graph."""
    return SceneStoryboard(
        target_duration_seconds=20,
        steps=(
            SceneStep(
                goal="A point on the unit circle traces a sine curve",
                duration_seconds=20,
                visual_kind=VisualKind.FUNCTION,
                objects=(
                    SceneObject(
                        id="circle",
                        type=IrObjectType.CIRCLE,
                        radius=1.0,
                        x=-4.0,
                        y=0.0,
                        color="WHITE",
                    ),
                    SceneObject(id="axes", type=IrObjectType.AXES),
                    SceneObject(
                        id="curve",
                        type=IrObjectType.PLOT,
                        parent_id="axes",
                        formula="sin",
                        color="BLUE",
                    ),
                    SceneObject(id="point", type=IrObjectType.DOT, color="RED"),
                ),
                trackers=(TrackerSpec(id="t", initial=0.0, minimum=0.0, maximum=3.0),),
                bindings=(
                    BindingSpec(
                        object_id="point",
                        tracker_id="t",
                        expr_id=IrExprId.SINE,
                        role="position",
                    ),
                ),
                state_changes=(
                    StateChange(
                        kind=IrStateChangeKind.CREATE,
                        target_ids=("circle", "axes", "curve", "point"),
                        run_time=2.0,
                    ),
                    StateChange(
                        kind=IrStateChangeKind.SET_VALUE, tracker_id="t", value=3.0, run_time=3.0
                    ),
                ),
            ),
        ),
    )


def mixed_formula_geometry_threed_storyboard() -> SceneStoryboard:
    """One prompt, three shots: formula, geometry, 3D — split for concat."""
    formula = opening_manim_formula_storyboard().steps[0]
    geometry = polygon_on_axes_storyboard().steps[0]
    three_d = fixed_in_frame_storyboard().steps[0]
    return SceneStoryboard(
        target_duration_seconds=48,
        steps=(formula, geometry, three_d),
    )


def pythagorean_proof_storyboard() -> SceneStoryboard:
    return SceneStoryboard(
        target_duration_seconds=20,
        steps=(
            SceneStep(
                goal="Prove the Pythagorean theorem with a right triangle",
                duration_seconds=20,
                visual_kind=VisualKind.GEOMETRY_PROOF,
                objects=(
                    SceneObject(
                        id="triangle",
                        type=IrObjectType.POLYGON,
                        vertices=((-2.0, -1.0), (2.0, -1.0), (-2.0, 2.0)),
                        color="WHITE",
                    ),
                    SceneObject(id="right_angle", type=IrObjectType.RIGHT_ANGLE, color="YELLOW"),
                ),
                given=("直角三角形 ABC，直角在 C。",),
                prove="AB^2 = AC^2 + BC^2",
                proof_steps=(
                    ProofStep(
                        statement="以三边向外作正方形",
                        reason="面积定义",
                        object_ids=("triangle",),
                    ),
                    ProofStep(
                        statement="两个小正方形面积之和等于斜边上正方形",
                        reason="割补",
                        object_ids=("triangle", "right_angle"),
                    ),
                ),
                state_changes=(
                    StateChange(
                        kind=IrStateChangeKind.CREATE,
                        target_ids=("triangle", "right_angle"),
                        run_time=1.5,
                    ),
                ),
            ),
        ),
    )


GALLERY_STORYBOARDS = {
    "BraceAnnotation": brace_annotation_storyboard,
    "VectorArrow": vector_arrow_storyboard,
    "PointMovingOnShapes": point_moving_on_shapes_storyboard,
    "MovingAround": moving_around_storyboard,
    "MovingAngle": moving_angle_storyboard,
    "MovingDots": moving_dots_storyboard,
    "MovingFrameBox": moving_frame_box_storyboard,
    "SinAndCosFunctionPlot": sin_and_cos_function_plot_storyboard,
    "ArgMinExample": arg_min_example_storyboard,
    "GraphAreaPlot": graph_area_plot_storyboard,
    "PolygonOnAxes": polygon_on_axes_storyboard,
    "FollowingGraphCamera": following_graph_camera_storyboard,
    "FixedInFrameMObjectTest": fixed_in_frame_storyboard,
    "ThreeDCameraRotation": three_d_camera_rotation_storyboard,
    "ThreeDSurfacePlot": three_d_surface_plot_storyboard,
    "OpeningManim": opening_manim_formula_storyboard,
    "SineCurveUnitCircle": sine_curve_unit_circle_storyboard,
}
