from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "apps/web/src"
APP_HEADER = WEB / "components/auth/app-header.tsx"
FEATURE_FLAGS = WEB / "lib/feature-flags.ts"
PLACEHOLDER = WEB / "components/feature-foundation/feature-placeholder.tsx"
LAB_PAGE = WEB / "app/lab/page.tsx"
STUDIO_PAGE = WEB / "app/studio/page.tsx"
SESSION_HOOK = WEB / "hooks/workbench/use-workbench-session.ts"

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _flag_results(values: list[str | None]) -> list[bool]:
    expressions = ["undefined" if value is None else json.dumps(value) for value in values]
    source_path = json.dumps(str(FEATURE_FLAGS))
    script = f"""
const fs = require("fs");
const ts = require("typescript");
const source = fs.readFileSync({source_path}, "utf8");
const compiled = ts.transpileModule(source, {{
  compilerOptions: {{ module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }}
}});
const module = {{ exports: {{}} }};
new Function("module", "exports", compiled.outputText)(module, module.exports);
const values = [{", ".join(expressions)}];
const results = values.map((value) => module.exports.isFeatureFlagEnabled(value));
process.stdout.write(JSON.stringify(results));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_feature_flag_parser_requires_exact_lowercase_true() -> None:
    values = [None, "", "false", "TRUE", "True", "1", " true", "true ", "true"]

    assert _flag_results(values) == [False, False, False, False, False, False, False, False, True]


def test_navigation_reads_two_independent_flags_and_omits_disabled_links() -> None:
    source = _read(APP_HEADER)

    assert 'process.env.NEXT_PUBLIC_EXPERIMENT_LAB_ENABLED' in source
    assert 'process.env.NEXT_PUBLIC_STUDIO_ENABLED' in source
    assert '{labEnabled ? <Link href="/lab">实验室</Link> : null}' in source
    assert '{studioEnabled ? <Link href="/studio">Studio</Link> : null}' in source
    assert source.count("isFeatureFlagEnabled(") == 2


def test_disabled_routes_call_server_not_found_before_mounting_protected_content() -> None:
    for page, flag_name, placeholder_name in (
        (LAB_PAGE, "NEXT_PUBLIC_EXPERIMENT_LAB_ENABLED", "LabPlaceholder"),
        (STUDIO_PAGE, "NEXT_PUBLIC_STUDIO_ENABLED", "StudioPlaceholder"),
    ):
        source = _read(page)

        assert 'import { notFound } from "next/navigation";' in source
        assert f'process.env.{flag_name}' in source
        assert "notFound();" in source
        assert source.index("notFound();") < source.index(f"return <{placeholder_name}")
        assert '"use client"' not in source


def test_enabled_pages_use_the_existing_session_recovery_contract() -> None:
    lab_page = _read(LAB_PAGE)
    studio_page = _read(STUDIO_PAGE)
    placeholder = _read(PLACEHOLDER)
    session_hook = _read(SESSION_HOOK)

    assert "LabPlaceholder" in lab_page
    assert "StudioPlaceholder" in studio_page
    assert 'useWorkbenchSession' in placeholder
    assert 'session.state === "loading"' in placeholder
    assert 'session.state === "error"' in placeholder
    assert 'session.state === "ready"' in placeholder
    assert 'id="main-content"' in placeholder
    assert 'aria-busy={session.state === "loading"}' in placeholder
    assert '<StatusMessage tone="error">' in placeholder
    assert '"/login"' in session_hook
    assert '"/change-password"' in session_hook


def test_placeholders_truthfully_describe_milestone_one_scope() -> None:
    source = _read(PLACEHOLDER)

    assert "科学运行时、求解器、实时交互或实时渲染未启用" in source
    assert "实验到讲解叙事的工作流或 Manim 视频生成未启用" in source
    assert "WebSocket" not in source
    assert "DeepSeek" not in source
    assert "PDE" not in source
    assert "GPU" not in source


def test_new_web_sources_do_not_add_execution_or_client_credential_paths() -> None:
    source = "\n".join(
        _read(path) for path in (APP_HEADER, FEATURE_FLAGS, PLACEHOLDER, LAB_PAGE, STUDIO_PAGE)
    )

    for forbidden in (
        "localStorage",
        "sessionStorage",
        "Authorization",
        "owner_id",
        "workbenchApi",
        "WebSocket",
        "EventSource",
        "fetch(",
        "/api/",
        "execute(",
        "render(",
    ):
        assert forbidden not in source


def test_workbench_sources_are_unchanged_from_task_three_base() -> None:
    paths = [
        *sorted((WEB / "app/workbench").rglob("*.ts*")),
        *sorted((WEB / "components/workbench").rglob("*.ts*")),
        *sorted((WEB / "hooks/workbench").rglob("*.ts*")),
    ]

    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        completed = subprocess.run(
            ["git", "show", f"2828bdc:{relative}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        assert completed.stdout.decode() == _read(path), relative
