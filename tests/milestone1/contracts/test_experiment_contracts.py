from datetime import datetime, timezone
from uuid import uuid4

import pytest
from manim_workbench_contracts import (
    CONTRACT_SCHEMA_VERSION,
    AssumptionSource,
    AssumptionStatus,
    Experiment,
    ExperimentAssumption,
    ExperimentCodeFile,
    ExperimentCreateRequest,
    ExperimentDomainKind,
    ExperimentDraft,
    ExperimentDraftUpdateRequest,
    ExperimentObservable,
    ExperimentPage,
    ExperimentParameter,
    ExperimentPatchOperation,
    ExperimentPatchOperationKind,
    ExperimentPatchProposal,
    ExperimentPatchProposalApplyRequest,
    ExperimentPatchProposalPage,
    ExperimentPatchProposalRejectRequest,
    ExperimentPatchProposalStatus,
    ExperimentVersion,
    ExperimentVersionCreateRequest,
    ExperimentVersionPage,
    ModelSpec,
    Project,
)
from manim_workbench_contracts.generation import build_json_schema, build_typescript
from pydantic import ValidationError


def test_schema_16_preserves_existing_project_contract_behavior() -> None:
    """Catches an accidental schema bump that changes existing model semantics."""
    created_at = datetime(2026, 8, 10, tzinfo=timezone.utc)
    project = Project(
        id=uuid4(),
        owner_id=uuid4(),
        title="Existing project",
        created_at=created_at,
    )

    assert CONTRACT_SCHEMA_VERSION == "1.6"
    assert project.model_dump(mode="json") == {
        "id": str(project.id),
        "owner_id": str(project.owner_id),
        "title": "Existing project",
        "created_at": "2026-08-10T00:00:00Z",
        "archived_at": None,
    }
    with pytest.raises(ValidationError):
        Project(
            id=uuid4(),
            owner_id=uuid4(),
            title="Existing project",
            created_at=created_at,
            unexpected=True,
        )
    with pytest.raises(ValidationError):
        project.title = "Changed"


def test_model_spec_accepts_nested_finite_json_values_without_coercing_booleans() -> None:
    """Catches a JSON escape hatch that loses boolean values or nested structure."""
    specification = ModelSpec(
        schema_version="1.0",
        domain_kind=ExperimentDomainKind.ODE,
        plugin_id="solver.rk4",
        plugin_version="1.2.3",
        payload={
            "enabled": True,
            "step": 0.25,
            "initial": [1, {"nested": [False, None]}],
        },
    )

    assert specification.payload["enabled"] is True
    assert specification.model_dump(mode="json")["payload"]["initial"] == [
        1,
        {"nested": [False, None]},
    ]


@pytest.mark.parametrize("invalid_number", [float("nan"), float("inf"), float("-inf")])
def test_model_spec_rejects_non_finite_json_numbers(invalid_number: float) -> None:
    """Catches accepting JSON values that cannot be serialized canonically."""
    with pytest.raises(ValidationError):
        ModelSpec(
            schema_version="1.0",
            domain_kind=ExperimentDomainKind.GENERIC,
            plugin_id="solver.basic",
            plugin_version="1",
            payload={"number": invalid_number},
        )


def test_model_spec_rejects_invalid_plugin_ids_and_oversized_canonical_payloads() -> None:
    """Catches bypasses of plugin identity and JSON payload boundaries."""
    with pytest.raises(ValidationError):
        ModelSpec(
            schema_version="1.0",
            domain_kind=ExperimentDomainKind.GENERIC,
            plugin_id="AA",
            plugin_version="1",
            payload={},
        )
    with pytest.raises(ValidationError):
        ModelSpec(
            schema_version="1.0",
            domain_kind=ExperimentDomainKind.GENERIC,
            plugin_id="solver.basic",
            plugin_version="1",
            payload={"value": "x" * 200_000},
        )


def _model_spec() -> ModelSpec:
    return ModelSpec(
        schema_version="1.0",
        domain_kind=ExperimentDomainKind.GEOMETRY,
        plugin_id="geometry.triangle",
        plugin_version="1.0",
        payload={"vertices": 3},
    )


def _code_file(path: str = "model.py") -> ExperimentCodeFile:
    return ExperimentCodeFile(path=path, language="python", content="MODEL = 1\n")


def test_experiment_create_and_page_contracts_apply_defaults_and_bounds() -> None:
    """Catches experiment creation that loses its generic default or unbounded pagination."""
    request = ExperimentCreateRequest(title="Heat equation")
    experiment = Experiment(
        id=uuid4(),
        project_id=uuid4(),
        owner_id=uuid4(),
        title=request.title,
        created_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )

    assert request.domain_kind is ExperimentDomainKind.GENERIC
    assert ExperimentPage(items=(experiment,), next_cursor=experiment.id).items == (experiment,)
    with pytest.raises(ValidationError):
        ExperimentPage(items=(experiment,) * 101)


def test_experiment_draft_rejects_duplicate_or_unsafe_code_paths() -> None:
    """Catches drafts that permit ambiguous or escaping source files."""
    experiment_id = uuid4()
    draft = ExperimentDraft(
        experiment_id=experiment_id,
        project_id=uuid4(),
        owner_id=uuid4(),
        revision=1,
        model_spec=_model_spec(),
        parameters=(ExperimentParameter(key="time.step", label="Time step", value=0.25),),
        observables=(ExperimentObservable(key="temperature", label="Temperature", unit="K"),),
        assumptions=(
            ExperimentAssumption(
                id=uuid4(),
                statement="The material is homogeneous.",
                source=AssumptionSource.USER,
                status=AssumptionStatus.ACCEPTED,
                created_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            ),
        ),
        visualization={"showGrid": True},
        code_files=(_code_file(),),
        updated_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )

    assert draft.visualization == {"showGrid": True}
    duplicate_path_payload = draft.model_dump()
    duplicate_path_payload["code_files"] = (_code_file("model.py"), _code_file("model.py"))
    with pytest.raises(ValidationError):
        ExperimentDraft(**duplicate_path_payload)
    with pytest.raises(ValidationError):
        _code_file("../outside.py")


def test_draft_update_distinguishes_omitted_fields_from_explicit_empty_replacements() -> None:
    """Catches no-op patches and a loss of intentional empty collection replacements."""
    with pytest.raises(ValidationError):
        ExperimentDraftUpdateRequest(expected_revision=1)

    replacement = ExperimentDraftUpdateRequest(
        expected_revision=2,
        parameters=(),
        observables=(),
        assumptions=(),
        visualization={},
        code_files=(),
    )

    assert replacement.model_fields_set == {
        "expected_revision",
        "parameters",
        "observables",
        "assumptions",
        "visualization",
        "code_files",
    }
    assert replacement.parameters == ()
    assert replacement.visualization == {}
    with pytest.raises(ValidationError):
        ExperimentDraftUpdateRequest(
            expected_revision=3,
            code_files=(_code_file("main.py"), _code_file("main.py")),
        )


def test_generated_json_value_is_recursive_and_bounded_in_typescript_and_schema() -> None:
    """Catches generator output that erases JSON object shape behind unsafe TS types."""
    schema = build_json_schema()
    typescript = build_typescript(schema)
    json_value = schema["$defs"]["JsonValue"]
    object_branch = next(item for item in json_value["anyOf"] if item.get("type") == "object")

    assert object_branch["additionalProperties"] == {"$ref": "#/$defs/JsonValue"}
    assert "export interface JsonObject {" in typescript
    assert "readonly [key: `${string}`]: JsonValue;" in typescript
    assert "ReadonlyArray<JsonValue> | JsonObject | null" in typescript
    assert ": any" not in typescript
    assert ": unknown" not in typescript
    assert "[key: string]" not in typescript


def test_generated_json_value_coalesces_integer_and_number_branches() -> None:
    """Catches redundant TypeScript primitives emitted for one JSON number type."""
    json_value_line = next(
        line
        for line in build_typescript(build_json_schema()).splitlines()
        if line.startswith("export type JsonValue")
    )

    assert json_value_line.count("number") == 1


def _experiment_snapshot_fields() -> dict[str, object]:
    return {
        "model_spec": _model_spec(),
        "parameters": (),
        "observables": (),
        "assumptions": (),
        "visualization": {},
        "code_files": (),
    }


def _experiment_version(version: int, parent_version_id: object) -> ExperimentVersion:
    return ExperimentVersion(
        id=uuid4(),
        experiment_id=uuid4(),
        project_id=uuid4(),
        owner_id=uuid4(),
        version=version,
        parent_version_id=parent_version_id,
        draft_revision=1,
        content_hash="a" * 64,
        created_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        **_experiment_snapshot_fields(),
    )


def test_experiment_versions_enforce_parent_invariants_and_pagination_bounds() -> None:
    """Catches an immutable experiment history that can branch from no parent."""
    first = _experiment_version(version=1, parent_version_id=None)
    later = _experiment_version(version=2, parent_version_id=first.id)

    assert ExperimentVersionPage(items=(first, later), next_cursor=2).next_cursor == 2
    assert ExperimentVersionCreateRequest(expected_revision=1).expected_revision == 1
    with pytest.raises(ValidationError):
        _experiment_version(version=1, parent_version_id=uuid4())
    with pytest.raises(ValidationError):
        _experiment_version(version=2, parent_version_id=None)
    with pytest.raises(ValidationError):
        ExperimentVersionCreateRequest(expected_revision=0)
    with pytest.raises(ValidationError):
        ExperimentVersionPage(items=(first,) * 101)


def test_patch_operations_require_values_by_operation_kind() -> None:
    """Catches JSON Patch operations that silently discard or invent a value."""
    add = ExperimentPatchOperation(
        operation=ExperimentPatchOperationKind.ADD,
        path="/visualization/showGrid",
        value=True,
    )
    replace_with_null = ExperimentPatchOperation(
        operation=ExperimentPatchOperationKind.REPLACE,
        path="/parameters/0/value",
        value=None,
    )
    remove = ExperimentPatchOperation(
        operation=ExperimentPatchOperationKind.REMOVE,
        path="/parameters/0",
    )

    assert add.value is True
    assert replace_with_null.value is None
    assert "value" not in remove.model_dump(mode="json")
    with pytest.raises(ValidationError):
        ExperimentPatchOperation(operation=ExperimentPatchOperationKind.ADD, path="/parameters/0")
    with pytest.raises(ValidationError):
        ExperimentPatchOperation(
            operation=ExperimentPatchOperationKind.REMOVE,
            path="/parameters/0",
            value=False,
        )
    with pytest.raises(ValidationError):
        ExperimentPatchOperation(
            operation=ExperimentPatchOperationKind.REPLACE,
            path="parameters/0",
            value=1,
        )


def test_patch_proposal_lifecycle_requires_matching_resolution_timestamp() -> None:
    """Catches proposal statuses that no longer identify whether they were resolved."""
    operation = ExperimentPatchOperation(
        operation=ExperimentPatchOperationKind.REPLACE,
        path="/visualization/showGrid",
        value=False,
    )
    created_at = datetime(2026, 8, 10, tzinfo=timezone.utc)
    pending = ExperimentPatchProposal(
        id=uuid4(),
        experiment_id=uuid4(),
        project_id=uuid4(),
        owner_id=uuid4(),
        expected_revision=1,
        status=ExperimentPatchProposalStatus.PENDING,
        operations=(operation,),
        assumptions=(),
        source=AssumptionSource.MODEL,
        created_at=created_at,
    )
    applied = ExperimentPatchProposal(
        id=uuid4(),
        experiment_id=uuid4(),
        project_id=uuid4(),
        owner_id=uuid4(),
        expected_revision=2,
        status=ExperimentPatchProposalStatus.APPLIED,
        operations=(operation,),
        assumptions=(),
        source=AssumptionSource.SYSTEM,
        created_at=created_at,
        resolved_at=created_at,
    )

    assert ExperimentPatchProposalPage(items=(pending, applied)).items == (pending, applied)
    assert ExperimentPatchProposalApplyRequest(expected_revision=1).expected_revision == 1
    assert ExperimentPatchProposalRejectRequest(expected_revision=1, reason="Not applicable").reason
    missing_resolution_payload = pending.model_dump()
    missing_resolution_payload["status"] = ExperimentPatchProposalStatus.APPLIED
    with pytest.raises(ValidationError):
        ExperimentPatchProposal(**missing_resolution_payload)
    pending_resolution_payload = applied.model_dump()
    pending_resolution_payload["status"] = ExperimentPatchProposalStatus.PENDING
    with pytest.raises(ValidationError):
        ExperimentPatchProposal(**pending_resolution_payload)
    with pytest.raises(ValidationError):
        ExperimentPatchProposalRejectRequest(expected_revision=1, reason="x" * 2_001)
