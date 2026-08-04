"""Static guards for the fixed ManimGL Phase 2 benchmark implementation."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "scenes.py"
RUNNER = ROOT / "scripts" / "run_benchmark.sh"


class ManimGLBenchmarkContractTests(unittest.TestCase):
    def test_all_contract_scenes_are_declared(self) -> None:
        module = ast.parse(SCENES.read_text(encoding="utf-8"))
        classes = {node.name for node in module.body if isinstance(node, ast.ClassDef)}
        self.assertTrue(
            {
                "FormulaTransform",
                "Derivative",
                "FunctionPlot",
                "ParameterSweep",
                "Tangent",
                "Area",
            }.issubset(classes)
        )

    def test_runner_pins_the_release_and_avoids_result_fabrication(self) -> None:
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("v1.7.2", runner)
        self.assertIn("result.json", runner)
        self.assertIn("all 12 render attempts succeed", runner)


if __name__ == "__main__":
    unittest.main()
