from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLAN = ROOT / "benchmarks" / "phase8" / "browser_acceptance_plan.json"
SCRIPT = ROOT / "scripts" / "phase8_acceptance.py"


def test_browser_acceptance_plan_covers_frozen_phase8_gates() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))

    assert plan["execution"]["external_provider"] == "forbidden"
    assert plan["actors"] == ["teacher_a", "teacher_b"]
    assert plan["viewports"] == [320, 768, 1024, 1440]
    assert {
        "login",
        "first_password_change",
        "create_project",
        "create_prompt_version",
        "generate_content_plan",
        "generate_code_version",
        "submit_preview",
        "submit_final",
        "view_or_download_python",
    } <= set(plan["flow"])
    assert {
        "reload_after_each_terminal_job",
        "api_restart_then_reconnect_sse_from_last_event_id",
    } <= set(plan["recovery"])
    assert {"single_h1_then_ordered_headings", "aria_live_announces_job_state"} <= set(
        plan["accessibility"]
    )


def test_acceptance_script_reports_browser_availability_without_claiming_execution() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--browser"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    report = json.loads(result.stdout)
    local_runner = ROOT / "node_modules" / ".bin" / "playwright"
    local_browsers = tuple(
        (ROOT / "runtime" / "playwright-browsers").glob("chromium-*/chrome-*/chrome")
    )
    if local_runner.is_file() and any(browser.is_file() for browser in local_browsers):
        assert report["browser"]["status"] == "not_run"
        assert report["browser"]["reason_code"] == "local_services_required"
    else:
        assert report["browser"]["status"] == "skipped"
        assert report["browser"]["reason_code"] == "automation_dependency_unavailable"
    assert report["browser"]["executed"] is False
    assert report["blackbox_executed"] is False
    assert report["attack_cases_skipped"] == 0
    assert not any(
        value in result.stdout.lower()
        for value in ("prompt", "source", "session", "csrf", "path", "key", "sk-")
    )
