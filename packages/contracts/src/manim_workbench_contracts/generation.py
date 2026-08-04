from __future__ import annotations

import json
from typing import Any

from .models import CONTRACT_MODELS, CONTRACT_SCHEMA_VERSION


def build_json_schema() -> dict[str, Any]:
    definitions: dict[str, Any] = {}
    root_names: list[str] = []

    for model in CONTRACT_MODELS:
        model_schema = model.model_json_schema(ref_template="#/$defs/{model}")
        nested = model_schema.pop("$defs", {})
        for name, definition in nested.items():
            previous = definitions.get(name)
            if previous is not None and previous != definition:
                raise ValueError(f"Conflicting schema definition: {name}")
            definitions[name] = definition
        definitions[model.__name__] = model_schema
        root_names.append(model.__name__)

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://manim-workbench.local/contracts/{CONTRACT_SCHEMA_VERSION}",
        "title": "Manim Workbench Contracts",
        "x-contract-schema-version": CONTRACT_SCHEMA_VERSION,
        "x-contract-models": sorted(root_names),
        "$defs": dict(sorted(definitions.items())),
    }


def _typescript_type(schema: dict[str, Any]) -> str:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)
    if "enum" in schema:
        return " | ".join(json.dumps(value, ensure_ascii=False) for value in schema["enum"])
    if "anyOf" in schema:
        return " | ".join(_typescript_type(option) for option in schema["anyOf"])

    schema_type = schema.get("type")
    if schema_type == "string":
        return "string"
    if schema_type in {"integer", "number"}:
        return "number"
    if schema_type == "boolean":
        return "boolean"
    if schema_type == "null":
        return "null"
    if schema_type == "array":
        return f"ReadonlyArray<{_typescript_type(schema['items'])}>"

    raise ValueError(f"Unsupported JSON Schema shape: {schema}")


def build_typescript(schema: dict[str, Any]) -> str:
    lines = [
        "// Generated from Pydantic contracts. Do not edit.",
        f'export const CONTRACT_SCHEMA_VERSION = "{CONTRACT_SCHEMA_VERSION}" as const;',
        "",
    ]

    for name, definition in schema["$defs"].items():
        if definition.get("type") == "object":
            required = set(definition.get("required", []))
            lines.append(f"export interface {name} {{")
            for field_name, field_schema in definition.get("properties", {}).items():
                optional = "" if field_name in required else "?"
                lines.append(
                    f"  readonly {field_name}{optional}: {_typescript_type(field_schema)};"
                )
            lines.append("}")
        else:
            lines.append(f"export type {name} = {_typescript_type(definition)};")
        lines.append("")

    return "\n".join(lines)


def render_contract_artifacts() -> tuple[str, str]:
    schema = build_json_schema()
    schema_text = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return schema_text, build_typescript(schema)
