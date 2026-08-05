from __future__ import annotations

import argparse
import json
import sys
from importlib import import_module
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

acceptance = import_module("benchmarks.phase9.acceptance")

DEFAULT_CORPUS = ROOT / "benchmarks" / "phase9" / "golden_corpus.json"
DEFAULT_BASELINE = ROOT / "benchmarks" / "phase9" / "baseline_metrics.json"
REPORT_ROOT = ROOT / "benchmarks" / "phase9"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bounded offline Phase 9 acceptance.")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--records",
        type=Path,
        help="Optional redacted terminal-record JSON exported by an offline pipeline.",
    )
    parser.add_argument(
        "--write-report",
        type=Path,
        help="Optional JSON report destination below benchmarks/phase9.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        corpus = acceptance.load_corpus(args.corpus)
        baseline = acceptance.load_metrics_baseline(args.baseline)
        records = (
            acceptance.load_terminal_records(args.records)
            if args.records
            else acceptance.build_terminal_records(corpus)
        )
        report = acceptance.evaluate_acceptance(corpus=corpus, records=records, baseline=baseline)
        _write_report_if_requested(args.write_report, report)
    except acceptance.AcceptanceFailure as error:
        print(json.dumps({"schema_version": "1.0", "status": "failed", "error_code": str(error)}))
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


def _write_report_if_requested(destination: Path | None, report: dict[str, Any]) -> None:
    if destination is None:
        return
    try:
        resolved = destination.resolve()
        resolved.relative_to(REPORT_ROOT.resolve())
    except ValueError:
        raise acceptance.AcceptanceFailure("unsafe_report_destination") from None
    resolved.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
