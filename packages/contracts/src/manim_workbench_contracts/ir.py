"""State-driven Scene IR. Models fill these fields; only the compiler writes Python."""

from __future__ import annotations

from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import Field, model_validator

from .models import ContractModel, Sha256, ShortText, VisualKind

IrId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class IrObjectType(str, Enum):
    TITLE = "title"
    MATH_TEX = "math_tex"
    TEXT = "text"
    AXES = "axes"
    PLOT = "plot"
    DOT = "dot"
    LINE = "line"
    DASHED_LINE = "dashed_line"
    CIRCLE = "circle"
    POLYGON = "polygon"
    ANGLE = "angle"
    RIGHT_ANGLE = "right_angle"
    LABEL = "label"
    DECIMAL = "decimal"
    SURFACE = "surface"
    SPHERE = "sphere"
    CUBE = "cube"
    IMAGE_REF = "image_ref"
    EQUATION_PANEL = "equation_panel"
    GEOMETRY_FIGURE = "geometry_figure"


class IrExprId(str, Enum):
    IDENTITY = "identity"
    POW2 = "pow2"
    POW3 = "pow3"
    CUBIC_SLOPE = "cubic_slope"
    SINE = "sine"
    LINEAR = "linear"
    SECANT_SLOPE = "secant_slope"


class IrStateChangeKind(str, Enum):
    SET_VALUE = "set_value"
    TRANSFORM_MATCHING_TEX = "transform_matching_tex"
    LAGGED_START = "lagged_start"
    SUCCESSION = "succession"
    ANIMATION_GROUP = "animation_group"
    FADE_IN = "fade_in"
    CREATE = "create"
    WAIT = "wait"
    WRITE = "write"


class IrCameraOpKind(str, Enum):
    ZOOM_TO = "zoom_to"
    RESTORE_FRAME = "restore_frame"
    SET_ORIENTATION = "set_orientation"
    AMBIENT_ROTATE = "ambient_rotate"


class SceneObject(ContractModel):
    id: IrId
    type: IrObjectType
    text: Annotated[str | None, Field(max_length=2_000)] = None
    color: Annotated[str | None, Field(pattern=r"^[A-Z][A-Z0-9_]{0,31}$")] = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    radius: Annotated[float | None, Field(gt=0, le=20)] = None
    vertices: Annotated[tuple[tuple[float, float], ...], Field(max_length=16)] = ()
    asset_sha256: Sha256 | None = None
    parent_id: IrId | None = None
    formula: Annotated[str | None, Field(max_length=500)] = None

    @model_validator(mode="after")
    def validate_type_payload(self) -> SceneObject:
        if self.type is IrObjectType.IMAGE_REF and self.asset_sha256 is None:
            raise ValueError("image_ref requires asset_sha256")
        if self.type is IrObjectType.POLYGON and len(self.vertices) < 3:
            raise ValueError("polygon requires at least three vertices")
        return self


class TrackerSpec(ContractModel):
    id: IrId
    initial: float
    minimum: float | None = None
    maximum: float | None = None


class BindingSpec(ContractModel):
    object_id: IrId
    tracker_id: IrId
    expr_id: IrExprId = IrExprId.IDENTITY
    role: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")] = "position"


class StateChange(ContractModel):
    kind: IrStateChangeKind
    target_ids: Annotated[tuple[IrId, ...], Field(max_length=24)] = ()
    tracker_id: IrId | None = None
    value: float | None = None
    from_text: Annotated[str | None, Field(max_length=2_000)] = None
    to_text: Annotated[str | None, Field(max_length=2_000)] = None
    run_time: Annotated[float, Field(gt=0, le=4)] = 1.0
    lag_ratio: Annotated[float, Field(ge=0, le=1)] = 0.25
    wait_time: Annotated[float, Field(ge=0, le=4)] = 0.0


class CameraOp(ContractModel):
    kind: IrCameraOpKind
    object_id: IrId | None = None
    scale: Annotated[float | None, Field(gt=0, le=8)] = None
    phi_degrees: float | None = None
    theta_degrees: float | None = None
    rate: Annotated[float | None, Field(gt=0, le=2)] = None
    run_time: Annotated[float, Field(gt=0, le=4)] = 1.0


class ProofStep(ContractModel):
    statement: Annotated[str, Field(min_length=1, max_length=1_000)]
    reason: Annotated[str, Field(min_length=1, max_length=1_000)]
    object_ids: Annotated[tuple[IrId, ...], Field(max_length=16)] = ()


class GeometryConstruction(ContractModel):
    object_id: IrId
    kind: IrObjectType
    label: ShortText | None = None


class SceneStep(ContractModel):
    goal: Annotated[str, Field(min_length=1, max_length=1_000)]
    duration_seconds: Annotated[float, Field(gt=0, le=180)]
    visual_kind: VisualKind
    objects: Annotated[tuple[SceneObject, ...], Field(max_length=48)] = ()
    trackers: Annotated[tuple[TrackerSpec, ...], Field(max_length=12)] = ()
    bindings: Annotated[tuple[BindingSpec, ...], Field(max_length=24)] = ()
    state_changes: Annotated[tuple[StateChange, ...], Field(max_length=48)] = ()
    camera: Annotated[tuple[CameraOp, ...], Field(max_length=12)] = ()
    given: Annotated[tuple[ShortText, ...], Field(max_length=12)] = ()
    prove: Annotated[str | None, Field(max_length=1_000)] = None
    proof_steps: Annotated[tuple[ProofStep, ...], Field(max_length=24)] = ()
    constructions: Annotated[tuple[GeometryConstruction, ...], Field(max_length=24)] = ()

    @model_validator(mode="after")
    def validate_kind_payload(self) -> SceneStep:
        if self.visual_kind is VisualKind.GEOMETRY_PROOF:
            if not self.given or self.prove is None or not self.proof_steps:
                raise ValueError("geometry_proof requires given, prove, and proof_steps")
        if self.visual_kind is VisualKind.PLANE_GEOMETRY and not (
            self.objects or self.constructions
        ):
            raise ValueError("plane_geometry requires objects or constructions")
        return self


class SceneStoryboard(ContractModel):
    target_duration_seconds: Annotated[int, Field(ge=15, le=600)]
    steps: Annotated[tuple[SceneStep, ...], Field(min_length=1, max_length=24)]


class GeometryProofRating(ContractModel):
    given_complete: bool
    prove_matches: bool
    math_correct: Annotated[int, Field(ge=0, le=5)]
    visual_clear: Annotated[int, Field(ge=0, le=5)]
    notes: Annotated[str | None, Field(max_length=2_000)] = None

    @property
    def passed(self) -> bool:
        return self.math_correct >= 4 and self.given_complete and self.prove_matches


class UserAssetKind(str, Enum):
    IMAGE = "image"
    CONSTRUCTION_JSON = "construction_json"


class UserAsset(ContractModel):
    id: UUID
    project_id: UUID
    owner_id: UUID
    kind: UserAssetKind
    sha256: Sha256
    byte_size: Annotated[int, Field(ge=1, le=8_000_000)]
    content_type: Annotated[str, Field(pattern=r"^image/(png|jpeg)$|^application/json$")]
    original_filename: Annotated[str, Field(min_length=1, max_length=200)]
