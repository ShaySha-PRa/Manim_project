import argparse
import json
import tempfile
from pathlib import Path

from manim_workbench_api.agent.p2_acceptance import (
    default_p2_benchmark_path,
    evaluate_p2_benchmark,
)

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Animation Agent V2 P2 benchmark gates.")
    parser.add_argument("--gold", type=Path, default=default_p2_benchmark_path())
    arguments = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="agent-p2-") as tmp:
        report = evaluate_p2_benchmark(work_root=Path(tmp), gold_path=arguments.gold)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    if not report.meets_p2_gates:
        parser.error("P2 benchmark gates failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
