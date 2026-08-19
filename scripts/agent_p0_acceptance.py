from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
for extra in (
    ROOT / "packages" / "contracts" / "src",
    ROOT / "apps" / "api" / "src",
    ROOT / "apps" / "runner" / "src",
):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from manim_workbench_api.agent.p0_acceptance import (  # noqa: E402
    docker_image_ready,
    evaluate_gold,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Animation Agent V2 P0 gold-set rates.")
    parser.add_argument(
        "--gold",
        type=Path,
        default=ROOT / "eval" / "agent_p0_gold.jsonl",
        help="P0 gold JSONL",
    )
    parser.add_argument("--skip-render", action="store_true", help="Compile and science only")
    parser.add_argument(
        "--require-render",
        action="store_true",
        help="Fail if the Manim Docker image is missing",
    )
    parser.add_argument("--write-report", type=Path, help="Optional JSON report path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    render = not args.skip_render
    if render and not docker_image_ready():
        if args.require_render:
            print(json.dumps({"status": "failed", "error_code": "manim_image_missing"}))
            return 2
        render = False
    with tempfile.TemporaryDirectory(prefix="agent-p0-") as tmp:
        report = evaluate_gold(gold_path=args.gold, work_root=Path(tmp), render=render)
    payload = report.as_dict()
    payload["status"] = "passed" if (
        report.meets_p0_gates if render else report.meets_compile_gates
    ) else "failed"
    if args.write_report is not None:
        args.write_report.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    if render:
        return 0 if report.meets_p0_gates else 1
    return 0 if report.meets_compile_gates else 1


if __name__ == "__main__":
    raise SystemExit(main())
