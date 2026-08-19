"""AnimationIR 2.0: declarative scene graph, reactive state, and timeline."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .models import ContractModel, Sha256

AnimId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class VisualPattern(str, Enum):
    FIELD_EVOLUTION = "field_evolution"
    FORMULA_MORPH = "formula_morph"
    TRAJECTORY_TRACE = "trajectory_trace"
    THREED_ORBIT = "3d_orbit"
    COMPARISON = "comparison"
    DATA_ANOMALY = "data_anomaly"


class DataKind(str, Enum):
    ARRAY = "array"
    SERIES = "series"
    TRAJECTORY = "trajectory"
    TRAJECTORY_SET = "trajectory_set"
    TABLE = "table"


class ObjectType(str, Enum):
    TITLE = "title"
    SCALAR_FIELD = "scalar_field"
    GRAPH = "graph"
    POINT = "point"
    PATH = "path"
    TRAJECTORY_SET = "trajectory_set"
    TIMESERIES = "timeseries"
    REGION = "region"
    ARROW_FRAME = "arrow_frame"
    NUMERIC_PANEL = "numeric_panel"


class StateType(str, Enum):
    SCALAR = "scalar"
    INTEGER = "integer"


class BindingOp(str, Enum):
    SAMPLE = "sample"
    IDENTITY = "identity"


class TimelineOpKind(str, Enum):
    CREATE = "create"
    ANIMATE_STATE = "animate_state"
    TRACE = "trace"
    COMPARE = "compare"
    HIGHLIGHT = "highlight"
    REVEAL = "reveal"
    WAIT = "wait"


class CameraOpKind(str, Enum):
    STATIC = "static"
    FOLLOW = "follow"
    ZOOM = "zoom"
    AMBIENT_ROTATE = "ambient_rotate"
    SET_ORIENTATION = "set_orientation"


class AssertionType(str, Enum):
    LINEAR_SUPERPOSITION = "linear_superposition"
    HARMONIC_COEFFICIENTS = "harmonic_coefficients"
    GIBBS_OVERSHOOT = "gibbs_overshoot"
    TRAJECTORY_ERROR = "trajectory_error"
    METRIC_MATCH = "metric_match"
    DATA_FIDELITY = "data_fidelity"
    FRENET_ORTHONORMAL = "frenet_orthonormal"
    RESIDUAL_MATCHES_TOOL = "residual_matches_tool"


class FallbackStrategy(str, Enum):
    STATIC_FRAME = "static_frame"
    DISCRETE_SAMPLES = "discrete_samples"
    FIXED_CAMERA = "fixed_camera"
    PRECOMPUTED_ONLY = "precomputed_only"


class SceneHint(ContractModel):
    dimension: Literal["2d", "3d"] = "2d"
    renderer_hint: Literal["manim", "web"] = "manim"


class DataRef(ContractModel):
    id: AnimId
    kind: DataKind
    artifact_ref: Annotated[str, Field(min_length=1, max_length=200)]
    output_sha256: Sha256 | None = None


class StateSpec(ContractModel):
    id: AnimId
    type: StateType = StateType.SCALAR
    initial: float = 0.0
    range: tuple[float, float] | None = None


class AnimObject(ContractModel):
    id: AnimId
    type: ObjectType
    data_ref: AnimId | None = None
    text: Annotated[str | None, Field(max_length=500)] = None
    color: Annotated[str | None, Field(pattern=r"^[A-Z][A-Z0-9_]{0,31}$")] = None


class BindingSource(ContractModel):
    op: BindingOp = BindingOp.SAMPLE
    data: AnimId | None = None
    state: AnimId | None = None


class AnimBinding(ContractModel):
    target: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.]{0,80}$")]
    source: BindingSource


class TimelineOp(ContractModel):
    op: TimelineOpKind
    target: AnimId | None = None
    targets: Annotated[tuple[AnimId, ...], Field(max_length=12)] = ()
    duration: Annotated[float, Field(gt=0, le=20)] = 1.0
    to: float | None = None
    wait_time: Annotated[float, Field(ge=0, le=8)] = 0.0


class AnimCameraOp(ContractModel):
    op: CameraOpKind = CameraOpKind.STATIC
    target: AnimId | None = None
    rate: Annotated[float | None, Field(gt=0, le=2)] = None
    phi_degrees: float | None = None
    theta_degrees: float | None = None
    run_time: Annotated[float, Field(gt=0, le=8)] = 1.0


class AnimAssertion(ContractModel):
    type: AssertionType
    target: AnimId | None = None
    fields: Annotated[tuple[str, ...], Field(max_length=8)] = ()


class AnimFallback(ContractModel):
    on: Annotated[str, Field(min_length=1, max_length=80)]
    strategy: FallbackStrategy


class AnimationIR(ContractModel):
    schema_version: Literal["2.0"] = "2.0"
    domain: Annotated[str, Field(min_length=1, max_length=80)]
    goal: Annotated[str, Field(min_length=1, max_length=1_000)]
    pattern: VisualPattern
    scene: SceneHint = SceneHint()
    data: Annotated[tuple[DataRef, ...], Field(max_length=12)] = ()
    states: Annotated[tuple[StateSpec, ...], Field(max_length=8)] = ()
    objects: Annotated[tuple[AnimObject, ...], Field(max_length=24)] = ()
    bindings: Annotated[tuple[AnimBinding, ...], Field(max_length=24)] = ()
    timeline: Annotated[tuple[TimelineOp, ...], Field(min_length=1, max_length=24)]
    camera: Annotated[tuple[AnimCameraOp, ...], Field(max_length=8)] = ()
    assertions: Annotated[tuple[AnimAssertion, ...], Field(max_length=12)] = ()
    fallbacks: Annotated[tuple[AnimFallback, ...], Field(max_length=8)] = ()

    @model_validator(mode="after")
    def validate_references(self) -> AnimationIR:
        data_ids = {item.id for item in self.data}
        state_ids = {item.id for item in self.states}
        object_ids = {item.id for item in self.objects}
        if len(data_ids) != len(self.data):
            raise ValueError("data ids must be unique")
        if len(state_ids) != len(self.states):
            raise ValueError("state ids must be unique")
        if len(object_ids) != len(self.objects):
            raise ValueError("object ids must be unique")
        for obj in self.objects:
            if obj.data_ref is not None and obj.data_ref not in data_ids:
                raise ValueError(f"unknown data_ref: {obj.data_ref}")
        for binding in self.bindings:
            if binding.source.data is not None and binding.source.data not in data_ids:
                raise ValueError(f"unknown binding data: {binding.source.data}")
            if binding.source.state is not None and binding.source.state not in state_ids:
                raise ValueError(f"unknown binding state: {binding.source.state}")
        return self
