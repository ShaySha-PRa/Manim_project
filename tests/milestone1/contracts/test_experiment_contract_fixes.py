import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import uuid4

import pytest
from manim_workbench_contracts import (
    ExperimentDomainKind,
    ExperimentDraft,
    ExperimentDraftUpdateRequest,
    ExperimentParameter,
    ExperimentPatchOperation,
    ExperimentPatchOperationKind,
    ExperimentVersion,
    ModelSpec,
)
from manim_workbench_contracts.generation import build_json_schema, build_typescript
from pydantic import BaseModel, ValidationError

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "pre_m1_contract_schema.json"
JSON_ENTRYPOINTS = (
    "model_spec",
    "parameter",
    "draft",
    "draft_update",
    "version",
    "patch_operation",
)
M1_DEFINITIONS = {
    "AssumptionSource",
    "AssumptionStatus",
    "Experiment",
    "ExperimentAssumption",
    "ExperimentCodeFile",
    "ExperimentCreateRequest",
    "ExperimentDomainKind",
    "ExperimentDraft",
    "ExperimentDraftUpdateRequest",
    "ExperimentObservable",
    "ExperimentPage",
    "ExperimentParameter",
    "ExperimentPatchOperation",
    "ExperimentPatchOperationKind",
    "ExperimentPatchProposal",
    "ExperimentPatchProposalApplyRequest",
    "ExperimentPatchProposalPage",
    "ExperimentPatchProposalRejectRequest",
    "ExperimentPatchProposalStatus",
    "ExperimentVersion",
    "ExperimentVersionCreateRequest",
    "ExperimentVersionPage",
    "JsonValue",
    "ModelSpec",
}
M1_CONTRACT_MODELS = {
    "Experiment",
    "ExperimentCreateRequest",
    "ExperimentDraft",
    "ExperimentDraftUpdateRequest",
    "ExperimentPage",
    "ExperimentPatchProposal",
    "ExperimentPatchProposalApplyRequest",
    "ExperimentPatchProposalPage",
    "ExperimentPatchProposalRejectRequest",
    "ExperimentVersion",
    "ExperimentVersionCreateRequest",
    "ExperimentVersionPage",
}


def _model_spec(payload: dict[str, Any] | None = None) -> ModelSpec:
    return ModelSpec(
        schema_version="1.0",
        domain_kind=ExperimentDomainKind.GENERIC,
        plugin_id="core.generic",
        plugin_version="1.0",
        payload={} if payload is None else payload,
    )


def _build_json_entrypoint(name: str, value: dict[str, Any]) -> tuple[BaseModel, str]:
    if name == "model_spec":
        return _model_spec(value), "payload"
    if name == "parameter":
        return ExperimentParameter(key="input", label="Input", value=value), "value"
    if name == "draft_update":
        model = ExperimentDraftUpdateRequest(expected_revision=1, visualization=value)
        return model, "visualization"
    if name == "patch_operation":
        operation = ExperimentPatchOperation(
            operation=ExperimentPatchOperationKind.ADD,
            path="/visualization/input",
            value=value,
        )
        return operation, "value"

    snapshot_fields = {
        "experiment_id": uuid4(),
        "project_id": uuid4(),
        "owner_id": uuid4(),
        "model_spec": _model_spec(),
        "parameters": (),
        "observables": (),
        "assumptions": (),
        "visualization": value,
        "code_files": (),
    }
    if name == "draft":
        return (
            ExperimentDraft(
                revision=1,
                updated_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
                **snapshot_fields,
            ),
            "visualization",
        )
    if name == "version":
        return (
            ExperimentVersion(
                id=uuid4(),
                version=1,
                parent_version_id=None,
                draft_revision=1,
                content_hash="a" * 64,
                created_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
                **snapshot_fields,
            ),
            "visualization",
        )
    raise AssertionError(f"unhandled JSON entrypoint: {name}")


def _json_object_at_depth(depth: int) -> dict[str, Any]:
    value: Any = "leaf"
    for _ in range(depth - 1):
        value = [value]
    return {"value": value}


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def test_pre_m1_definitions_are_byte_semantically_frozen() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    schema = build_json_schema()

    assert set(schema) == {
        "$schema",
        "$id",
        "title",
        "x-contract-schema-version",
        "x-contract-models",
        "$defs",
    }
    assert schema["$schema"] == fixture["schema_uri"]
    assert schema["title"] == fixture["title"]
    assert schema["$id"] == "https://manim-workbench.local/contracts/1.6"
    assert schema["x-contract-schema-version"] == "1.6"
    assert set(schema["$defs"]) == set(fixture["definition_sha256"]) | M1_DEFINITIONS
    assert Counter(schema["x-contract-models"]) == Counter(
        [*fixture["contract_models"], *M1_CONTRACT_MODELS]
    )
    assert {
        name: _canonical_sha256(schema["$defs"][name])
        for name in fixture["definition_sha256"]
    } == fixture["definition_sha256"]


@pytest.mark.parametrize("entrypoint", JSON_ENTRYPOINTS)
def test_json_values_are_deeply_frozen_without_changing_wire_shape(entrypoint: str) -> None:
    wire_value = {"outer": [{"enabled": True, "count": 1}]}
    model, field_name = _build_json_entrypoint(entrypoint, wire_value)
    frozen_value = getattr(model, field_name)

    assert isinstance(frozen_value, MappingProxyType)
    assert isinstance(frozen_value["outer"], tuple)
    assert isinstance(frozen_value["outer"][0], MappingProxyType)
    assert frozen_value["outer"][0]["enabled"] is True
    assert type(frozen_value["outer"][0]["count"]) is int
    with pytest.raises(TypeError):
        frozen_value["new"] = "mutation"
    with pytest.raises(TypeError):
        frozen_value["outer"][0]["enabled"] = False
    with pytest.raises(TypeError):
        frozen_value["outer"][0] = {"enabled": False}

    assert model.model_dump(mode="json")[field_name] == wire_value
    assert json.loads(model.model_dump_json())[field_name] == wire_value


@pytest.mark.parametrize("entrypoint", JSON_ENTRYPOINTS)
def test_every_json_value_entrypoint_enforces_canonical_utf8_size(entrypoint: str) -> None:
    exact_limit = {"v": "界" * 66_664}
    over_limit = {"v": "界" * 66_665}

    assert (
        len(
            json.dumps(exact_limit, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        == 200_000
    )
    _build_json_entrypoint(entrypoint, exact_limit)
    with pytest.raises(ValidationError, match="at most 200000 UTF-8 bytes"):
        _build_json_entrypoint(entrypoint, over_limit)


@pytest.mark.parametrize("entrypoint", JSON_ENTRYPOINTS)
def test_every_json_value_entrypoint_enforces_maximum_depth_32(entrypoint: str) -> None:
    _build_json_entrypoint(entrypoint, _json_object_at_depth(32))
    with pytest.raises(ValidationError, match="maximum nesting depth is 32"):
        _build_json_entrypoint(entrypoint, _json_object_at_depth(33))


@pytest.mark.parametrize("model_name", ["draft", "version"])
def test_default_visualization_is_frozen_and_dumps_as_an_empty_object(model_name: str) -> None:
    snapshot_fields = {
        "experiment_id": uuid4(),
        "project_id": uuid4(),
        "owner_id": uuid4(),
        "model_spec": _model_spec(),
        "parameters": (),
        "observables": (),
        "assumptions": (),
        "code_files": (),
    }
    if model_name == "draft":
        model = ExperimentDraft(
            revision=1,
            updated_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            **snapshot_fields,
        )
    else:
        model = ExperimentVersion(
            id=uuid4(),
            version=1,
            parent_version_id=None,
            draft_revision=1,
            content_hash="a" * 64,
            created_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            **snapshot_fields,
        )

    assert isinstance(model.visualization, MappingProxyType)
    with pytest.raises(TypeError):
        model.visualization["mutated"] = True
    assert model.model_dump(mode="json")["visualization"] == {}


def test_json_boolean_values_remain_distinct_from_json_numbers() -> None:
    specification = _model_spec(
        {"true": True, "false": False, "one": 1, "zero": 0, "nested": [True, 1, False, 0]}
    )
    dumped = specification.model_dump(mode="json")["payload"]

    assert type(specification.payload["true"]) is bool
    assert type(specification.payload["false"]) is bool
    assert type(specification.payload["one"]) is int
    assert type(specification.payload["zero"]) is int
    assert [type(value) for value in specification.payload["nested"]] == [bool, int, bool, int]
    assert dumped == {
        "true": True,
        "false": False,
        "one": 1,
        "zero": 0,
        "nested": [True, 1, False, 0],
    }


def test_draft_update_rejects_null_and_requires_a_replacement_in_all_contracts() -> None:
    replacement_fields = {
        "model_spec",
        "parameters",
        "observables",
        "assumptions",
        "visualization",
        "code_files",
    }
    for field_name in replacement_fields:
        with pytest.raises(ValidationError):
            ExperimentDraftUpdateRequest(expected_revision=1, **{field_name: None})

    replacement = ExperimentDraftUpdateRequest(expected_revision=1, parameters=())
    assert replacement.model_dump(mode="json") == {
        "expected_revision": 1,
        "parameters": [],
    }

    schema = build_json_schema()["$defs"]["ExperimentDraftUpdateRequest"]
    assert schema["required"] == ["expected_revision"]
    assert {tuple(branch["required"]) for branch in schema["anyOf"]} == {
        (field_name,) for field_name in replacement_fields
    }
    for field_name in replacement_fields:
        assert "null" not in json.dumps(schema["properties"][field_name])

    typescript = build_typescript(build_json_schema())
    declaration = typescript.split("export type ExperimentDraftUpdateRequest =", 1)[1].split(
        "\n\n", 1
    )[0]
    assert " & (" in declaration
    for field_name in replacement_fields:
        assert f"readonly {field_name}:" in declaration
    assert "null" not in declaration


def test_patch_operation_schema_and_typescript_encode_value_presence_by_kind() -> None:
    schema = build_json_schema()["$defs"]["ExperimentPatchOperation"]
    add_replace, remove = schema["oneOf"]

    add_replace_operation = add_replace["properties"]["operation"]
    remove_operation = remove["properties"]["operation"]
    assert add_replace_operation["$ref"] == "#/$defs/ExperimentPatchOperationKind"
    assert add_replace_operation["enum"] == ["add", "replace"]
    assert add_replace["required"] == ["operation", "path", "value"]
    assert "default" not in add_replace["properties"]["value"]
    assert remove_operation["$ref"] == "#/$defs/ExperimentPatchOperationKind"
    assert remove_operation["const"] == "remove"
    assert remove["required"] == ["operation", "path"]
    assert "value" not in remove["properties"]

    typescript = build_typescript(build_json_schema())
    declaration = typescript.split("export type ExperimentPatchOperation =", 1)[1].split(
        "\n\n", 1
    )[0]
    assert 'readonly operation: "add" | "replace";' in declaration
    assert "readonly value: JsonValue;" in declaration
    assert 'readonly operation: "remove";' in declaration
    assert "value?:" not in declaration

    remove_model = ExperimentPatchOperation(
        operation=ExperimentPatchOperationKind.REMOVE,
        path="/visualization/input",
    )
    replace_null_model = ExperimentPatchOperation(
        operation=ExperimentPatchOperationKind.REPLACE,
        path="/visualization/input",
        value=None,
    )
    assert remove_model.model_dump(mode="json") == {
        "operation": "remove",
        "path": "/visualization/input",
    }
    assert replace_null_model.model_dump(mode="json")["value"] is None


def test_generated_typescript_has_exact_json_union_and_no_escape_hatch_keywords() -> None:
    schema = build_json_schema()
    typescript = build_typescript(schema)
    without_string_literals = re.sub(r'"(?:\\.|[^"\\])*"', '""', typescript)
    json_value_line = next(
        line for line in typescript.splitlines() if line.startswith("export type JsonValue =")
    )
    json_value_schema_types = [
        branch.get("type") for branch in schema["$defs"]["JsonValue"]["anyOf"]
    ]

    assert json_value_line == (
        "export type JsonValue = string | boolean | number | ReadonlyArray<JsonValue> | "
        "JsonObject | null;"
    )
    assert typescript.count("readonly [key: `${string}`]: JsonValue;") == 1
    assert json_value_schema_types == [
        "string",
        "boolean",
        "integer",
        "number",
        "array",
        "object",
        "null",
    ]
    assert re.search(r"\b(?:any|unknown)\b", without_string_literals) is None
    assert "[key: string]" not in typescript
