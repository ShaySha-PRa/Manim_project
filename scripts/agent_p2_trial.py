"""Lab trial harness. This is not an external scientific user study."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from manim_workbench_api.agent.p2_acceptance import (
    default_p2_benchmark_path,
    evaluate_p2_benchmark,
)

PROTOCOL = Path(__file__).resolve().parents[1] / "eval" / "p2_lab_trial.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the P2 lab trial protocol against the local benchmark."
    )
    parser.add_argument("--gold", type=Path, default=default_p2_benchmark_path())
    arguments = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="agent-p2-trial-") as tmp:
        report = evaluate_p2_benchmark(work_root=Path(tmp), gold_path=arguments.gold)
    payload = report.as_dict()
    payload["protocol"] = str(PROTOCOL)
    payload["disclaimer"] = (
        "Lab harness only. Does not claim external researchers, interviews, or field trials."
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not report.meets_p2_gates:
        parser.error("P2 lab trial gates failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
