"""Fast checks for the ManimCE benchmark implementation (no Docker required)."""

from pathlib import Path
import unittest


ROOT = Path(__file__).parent


class ManimCEStaticContractTests(unittest.TestCase):
    def test_all_contract_scenes_are_present(self):
        source = (ROOT / "scenes.py").read_text(encoding="utf-8")
        self.assertIn("SCENE_IDS: dict[str, type[Scene]] = {}", source)
        for scene_id in (
            "formula_transform",
            "derivative",
            "function_plot",
            "parameter_sweep",
            "tangent",
            "area",
        ):
            self.assertIn(f'SCENE_IDS["{scene_id}"]', source)

    def test_docker_image_is_pinned_to_required_version(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("FROM manimcommunity/manim:v0.20.1", dockerfile)
        self.assertNotIn(":latest", dockerfile)
        self.assertNotIn(":stable", dockerfile)
        runner = (ROOT / "run_benchmark.py").read_text(encoding="utf-8")
        self.assertIn("manimcommunity/manim@sha256:f18f53f2", runner)

    def test_runner_uses_headless_low_quality_independent_runs(self):
        runner = (ROOT / "run_benchmark.py").read_text(encoding="utf-8")
        self.assertIn('"-ql"', runner)
        self.assertIn('"--disable_caching"', runner)
        self.assertIn("range(1, 3)", runner)
        self.assertIn('MANIMCE_DOCKER", "docker"', runner)
        self.assertIn("shutil.rmtree(ARTIFACTS", runner)


if __name__ == "__main__":
    unittest.main()
