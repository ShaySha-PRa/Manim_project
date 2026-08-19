import json

import pytest
from manim_workbench_api.assets.service import AssetError, extract_constructions
from manim_workbench_contracts.ir import IrObjectType


def test_json_constructions_become_ir_objects() -> None:
    payload = json.dumps(
        {
            "constructions": [
                {"kind": "circle", "x": 0, "y": 0, "radius": 1.2, "label": "O"},
                {
                    "kind": "polygon",
                    "vertices": [[-1, 0], [1, 0], [0, 1]],
                    "label": "ABC",
                },
            ]
        }
    ).encode("utf-8")
    objects = extract_constructions(payload, "application/json")
    assert objects[0].type is IrObjectType.CIRCLE
    assert objects[1].type is IrObjectType.POLYGON


def test_png_bytes_become_image_ref() -> None:
    objects = extract_constructions(b"\x89PNG fake", "image/png")
    assert objects[0].type is IrObjectType.IMAGE_REF
    assert objects[0].asset_sha256 is not None


def test_executable_content_types_are_rejected() -> None:
    with pytest.raises(AssetError):
        extract_constructions(b"print('no')", "text/x-python")
