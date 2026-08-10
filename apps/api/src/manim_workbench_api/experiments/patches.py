from __future__ import annotations

from copy import deepcopy
from typing import Any

from manim_workbench_contracts import ExperimentPatchOperation, ExperimentPatchOperationKind

from .errors import EXPERIMENT_PATCH_INVALID
from .serialization import json_value

_EDITABLE_ROOTS = {
    "model_spec",
    "parameters",
    "observables",
    "assumptions",
    "visualization",
    "code_files",
}


def apply_patch(
    snapshot: dict[str, Any], operations: tuple[ExperimentPatchOperation, ...]
) -> dict[str, Any]:
    result = deepcopy(snapshot)
    try:
        for operation in operations:
            tokens = _tokens(operation.path)
            if not tokens or tokens[0] not in _EDITABLE_ROOTS:
                raise ValueError("path is outside editable snapshot")
            parent = _parent(result, tokens[:-1])
            key = tokens[-1]
            if operation.operation is ExperimentPatchOperationKind.ADD:
                _add(parent, key, _operation_value(operation))
            elif operation.operation is ExperimentPatchOperationKind.REPLACE:
                _replace(parent, key, _operation_value(operation))
            else:
                _remove(parent, key)
    except (KeyError, TypeError, ValueError):
        raise EXPERIMENT_PATCH_INVALID from None
    return result


def _tokens(path: str) -> list[str]:
    if not path.startswith("/"):
        raise ValueError("path must be a JSON Pointer")
    return [_decode_token(token) for token in path[1:].split("/")]


def _decode_token(token: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(token):
        character = token[index]
        if character != "~":
            result.append(character)
            index += 1
            continue
        if index + 1 >= len(token) or token[index + 1] not in {"0", "1"}:
            raise ValueError("invalid JSON Pointer escape")
        result.append("~" if token[index + 1] == "0" else "/")
        index += 2
    return "".join(result)


def _parent(document: dict[str, Any], tokens: list[str]) -> Any:
    current: Any = document
    for token in tokens:
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(token)
            current = current[token]
        elif isinstance(current, list):
            current = current[_array_index(token, len(current), allow_end=False)]
        else:
            raise TypeError("JSON Pointer parent is not a container")
    return current


def _array_index(token: str, length: int, *, allow_end: bool) -> int:
    if not token.isascii() or not token.isdecimal() or (len(token) > 1 and token.startswith("0")):
        raise ValueError("array index is invalid")
    index = int(token)
    if index < 0 or index > length or (index == length and not allow_end):
        raise ValueError("array index is out of range")
    return index


def _operation_value(operation: ExperimentPatchOperation) -> Any:
    dumped = operation.model_dump(mode="json")
    if "value" not in dumped:
        raise ValueError("operation value is missing")
    return json_value(dumped["value"])


def _add(parent: Any, key: str, value: Any) -> None:
    if isinstance(parent, dict):
        parent[key] = value
        return
    if isinstance(parent, list):
        if key == "-":
            parent.append(value)
            return
        parent.insert(_array_index(key, len(parent), allow_end=True), value)
        return
    raise TypeError("JSON Patch parent is not a container")


def _replace(parent: Any, key: str, value: Any) -> None:
    if isinstance(parent, dict):
        if key not in parent:
            raise KeyError(key)
        parent[key] = value
        return
    if isinstance(parent, list):
        parent[_array_index(key, len(parent), allow_end=False)] = value
        return
    raise TypeError("JSON Patch parent is not a container")


def _remove(parent: Any, key: str) -> None:
    if isinstance(parent, dict):
        if key not in parent:
            raise KeyError(key)
        del parent[key]
        return
    if isinstance(parent, list):
        del parent[_array_index(key, len(parent), allow_end=False)]
        return
    raise TypeError("JSON Patch parent is not a container")
