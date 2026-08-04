from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

GL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GL_ROOT))

from scripts.write_result import SCENES, write_result


class WriteResultTests(unittest.TestCase):
    def test_preserves_failed_runs_for_disqualification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            runs = []
            for scene in SCENES:
                for iteration in (1, 2):
                    success = not (scene == "area" and iteration == 2)
                    runs.append(
                        {
                            "scene_id": scene,
                            "iteration": iteration,
                            "success": success,
                            "exit_code": 0 if success else 1,
                            "duration_seconds": 1.0,
                            "command": "docker run",
                            "output_path": "video.mp4" if success else "",
                            "output_sha256": "a" * 64 if success else "",
                            "log_path": "run.log",
                        }
                    )
            (artifacts / "runs.jsonl").write_text(
                "".join(json.dumps(run) + "\n" for run in runs), encoding="utf-8"
            )
            (artifacts / "environment.json").write_text(
                json.dumps(
                    {
                        "engine_version": "v1.7.2",
                        "python_version": "3.10",
                        "ffmpeg_version": "4.4",
                        "latex_version": "TeX Live",
                        "font_versions": ["DejaVu Sans"],
                        "container_or_environment": "sha256:test",
                    }
                ),
                encoding="utf-8",
            )

            write_result(root)
            result = json.loads((root / "result.json").read_text(encoding="utf-8"))

        self.assertEqual(len(result["runs"]), 12)
        self.assertTrue(result["first_attempt_success"]["area"])
        self.assertEqual(sum(run["success"] for run in result["runs"]), 11)


if __name__ == "__main__":
    unittest.main()
