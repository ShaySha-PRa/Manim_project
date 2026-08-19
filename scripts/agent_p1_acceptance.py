import argparse
import json
import tempfile
from pathlib import Path

from manim_workbench_api.agent.p1_acceptance import (
    default_p1_gold_path,
    evaluate_p1_gold,
)

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Animation Agent V2 P1 gold-set gates.")
    parser.add_argument("--gold", type=Path, default=default_p1_gold_path())
    arguments = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="agent-p1-") as tmp:
        report = evaluate_p1_gold(work_root=Path(tmp), gold_path=arguments.gold)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    if not report.meets_p1_gates:
        parser.error("P1 gold gates failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
