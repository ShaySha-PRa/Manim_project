from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BLACKBOX = ROOT / "tests" / "phase8" / "blackbox"
BROWSER = ROOT / "tests" / "phase8" / "browser"


def _browser_report() -> dict[str, Any]:
    local_runner = ROOT / "node_modules" / ".bin" / "playwright"
    has_runner = shutil.which("playwright") is not None or local_runner.is_file()
    local_browsers = tuple(
        (ROOT / "runtime" / "playwright-browsers").glob("chromium-*/chrome-*/chrome")
    )
    has_browser = any(
        shutil.which(candidate) is not None
        for candidate in ("chromium", "chromium-browser", "google-chrome")
    ) or any(candidate.is_file() for candidate in local_browsers)
    if has_runner and has_browser:
        return {
            "status": "not_run",
            "reason_code": "local_services_required",
            "executed": False,
        }
    return {
        "status": "skipped",
        "reason_code": "automation_dependency_unavailable",
        "executed": False,
    }


def _summary_count(output: str, label: str) -> int:
    match = re.search(rf"(\d+) {label}", output)
    return int(match.group(1)) if match else 0


def _report(
    *,
    exit_code: int,
    elapsed_ms: int,
    browser_only: bool,
    passed: int = 0,
    failed: int = 0,
) -> dict[str, Any]:
    executed = not browser_only
    if not executed:
        passed = 0
        failed = 0
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "mode": "offline_blackbox",
        "blackbox_executed": executed,
        "attack_cases_total": 11,
        "attack_cases_passed": passed,
        "attack_cases_failed": failed,
        "attack_cases_skipped": 11 - passed - failed if executed else 0,
        "attack_pass_rate_percent": round((passed / 11) * 100, 1) if executed else 0,
        "performance": {"elapsed_ms": elapsed_ms},
        "browser": _browser_report(),
    }
    serialized = json.dumps(report, sort_keys=True)
    forbidden = ("prompt", "source", "session", "csrf", "path", "key", "sk-")
    if any(value in serialized.lower() for value in forbidden):
        raise RuntimeError("acceptance report violates redaction contract")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 8 independent offline acceptance.")
    parser.add_argument(
        "--browser", action="store_true", help="report browser execution availability"
    )
    args = parser.parse_args()
    if args.browser:
        print(json.dumps(_report(exit_code=0, elapsed_ms=0, browser_only=True), sort_keys=True))
        return 0

    started = time.perf_counter()
    blackbox = subprocess.run(
        [sys.executable, "-m", "pytest", "-s", "-q", str(BLACKBOX)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    browser_plan = subprocess.run(
        [sys.executable, "-m", "pytest", "-s", "-q", str(BROWSER)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    exit_code = blackbox.returncode or browser_plan.returncode
    report = _report(
        exit_code=exit_code,
        elapsed_ms=elapsed_ms,
        browser_only=False,
        passed=_summary_count(blackbox.stdout, "passed"),
        failed=_summary_count(blackbox.stdout, "failed"),
    )
    print(json.dumps(report, sort_keys=True))
    if exit_code:
        print("phase8 acceptance tests failed; inspect local pytest output", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
