from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_gold_set import ValidationError, validate_dataset


def valid_entry(*, entry_id: str, category: str) -> dict:
    return {
        "id": entry_id,
        "category": category,
        "persona": "高中数学教师",
        "audience": "k12",
        "difficulty": "introductory",
        "topic": "一次函数",
        "prompt": "展示一次函数图像随斜率变化的过程。",
        "teaching_goal": "帮助学生理解斜率与图像方向的关系。",
        "must_include": ["坐标轴", "y=kx+b"],
        "must_avoid": ["把斜率与截距混淆"],
        "expected_scene_structure": [
            "给出函数表达式",
            "固定截距并改变斜率",
            "总结斜率和单调性的关系",
        ],
        "duration_seconds": {"min": 45, "target": 75, "max": 120},
        "correctness_checks": ["k>0 时函数递增", "k<0 时函数递减"],
        "ambiguities": ["用户未指定截距时默认 b=0"],
        "source": {
            "type": "synthetic_interview",
            "agent": "test-agent",
            "interview_id": "synthetic-test-01",
        },
        "review": {"status": "parent_validated", "notes": "测试样例"},
    }


def write_jsonl(path: Path, entries: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
        encoding="utf-8",
    )


class GoldSetValidationTests(unittest.TestCase):
    def test_accepts_balanced_30_entry_dataset(self) -> None:
        entries = [
            valid_entry(entry_id=f"formula_{index:03d}", category="formula_derivation")
            for index in range(1, 16)
        ] + [
            valid_entry(entry_id=f"function_{index:03d}", category="function_visualization")
            for index in range(1, 16)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gold.jsonl"
            write_jsonl(path, entries)
            report = validate_dataset(path)

        self.assertEqual(report.total, 30)
        self.assertEqual(report.by_category["formula_derivation"], 15)
        self.assertEqual(report.by_category["function_visualization"], 15)

    def test_rejects_duplicate_ids(self) -> None:
        entries = [
            valid_entry(entry_id="formula_001", category="formula_derivation"),
            valid_entry(entry_id="formula_001", category="formula_derivation"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gold.jsonl"
            write_jsonl(path, entries)
            with self.assertRaisesRegex(ValidationError, "duplicate id"):
                validate_dataset(path, enforce_phase1_counts=False)

    def test_rejects_invalid_duration_order(self) -> None:
        entry = valid_entry(entry_id="formula_001", category="formula_derivation")
        entry["duration_seconds"] = {"min": 120, "target": 60, "max": 90}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gold.jsonl"
            write_jsonl(path, [entry])
            with self.assertRaisesRegex(ValidationError, "duration"):
                validate_dataset(path, enforce_phase1_counts=False)

    def test_rejects_unreviewed_entries(self) -> None:
        entry = valid_entry(entry_id="formula_001", category="formula_derivation")
        entry["review"]["status"] = "candidate"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gold.jsonl"
            write_jsonl(path, [entry])
            with self.assertRaisesRegex(ValidationError, "parent_validated"):
                validate_dataset(path, enforce_phase1_counts=False)

    def test_rejects_id_with_valid_prefix_but_invalid_shape(self) -> None:
        entry = valid_entry(entry_id="formula_draft", category="formula_derivation")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gold.jsonl"
            write_jsonl(path, [entry])
            with self.assertRaisesRegex(ValidationError, "id must match"):
                validate_dataset(path, enforce_phase1_counts=False)

    def test_rejects_extra_nested_source_fields(self) -> None:
        entry = valid_entry(entry_id="formula_001", category="formula_derivation")
        entry["source"]["unexpected"] = "not allowed by schema"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gold.jsonl"
            write_jsonl(path, [entry])
            with self.assertRaisesRegex(ValidationError, "source fields"):
                validate_dataset(path, enforce_phase1_counts=False)


if __name__ == "__main__":
    unittest.main()
