from __future__ import annotations

import ast
from pathlib import Path
import runpy


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATEGORIES = {
    "formula": "formula_derivation",
    "functions": "function_visualization",
}


def load_manifest(category: str) -> tuple[dict[str, str], ...]:
    namespace = runpy.run_path(PROJECT_ROOT / "reference_scenes" / category / "manifest.py")
    return namespace["SCENE_MANIFEST"]


def test_reference_manifest_has_six_scenes_per_supported_category() -> None:
    entries = [entry for category in CATEGORIES for entry in load_manifest(category)]

    assert len(entries) == 12
    assert len({entry["scene_id"] for entry in entries}) == 12
    assert len({entry["scene_class"] for entry in entries}) == 12
    for category, expected_category in CATEGORIES.items():
        category_entries = load_manifest(category)
        assert len(category_entries) == 6
        assert {entry["category"] for entry in category_entries} == {expected_category}


def test_each_manifest_entry_identifies_one_scene_class_in_one_source_file() -> None:
    for category in CATEGORIES:
        category_dir = PROJECT_ROOT / "reference_scenes" / category
        sources = set(category_dir.glob("*.py")) - {category_dir / "manifest.py"}
        manifest = load_manifest(category)

        assert len(sources) == 6
        assert sources == {PROJECT_ROOT / entry["source_path"] for entry in manifest}
        for entry in manifest:
            source = PROJECT_ROOT / entry["source_path"]
            content = source.read_text(encoding="utf-8")
            tree = ast.parse(content)
            scene_classes = [
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef)
                and any(isinstance(base, ast.Name) and base.id == "Scene" for base in node.bases)
            ]
            assert [scene.name for scene in scene_classes] == [entry["scene_class"]]
            assert "manimlib" not in content
            assert not any(isinstance(node, ast.ImportFrom) and node.names[0].name == "*" for node in tree.body)
