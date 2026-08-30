from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "apps/web/src"
WORKBENCH = WEB / "app/workbench"
COMPONENTS = WEB / "components/workbench"
HOOKS = WEB / "hooks/workbench"


def _sources(*roots: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for root in roots for path in sorted(root.rglob("*.ts*"))
    )


def test_workbench_is_a_client_route_with_session_recovery() -> None:
    page = (WORKBENCH / "page.tsx").read_text(encoding="utf-8")
    hook = (HOOKS / "use-workbench-session.ts").read_text(encoding="utf-8")

    assert '"use client"' in page
    assert "workbenchApi.session" in hook
    assert '"/login"' in hook
    assert "workbenchApi.session" in hook


def test_workbench_keeps_identity_and_tokens_out_of_browser_state() -> None:
    source = _sources(WORKBENCH, COMPONENTS, HOOKS)

    assert "owner_id" not in source
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "Authorization" not in source


def test_python_is_read_only_and_the_regular_flow_has_no_json_editor() -> None:
    python_panel = (COMPONENTS / "python-read-only.tsx").read_text(encoding="utf-8")
    source = _sources(WORKBENCH, COMPONENTS, HOOKS)

    assert "<pre" in python_panel
    assert "<code" in python_panel
    assert "<textarea" not in python_panel
    assert "contentEditable" not in python_panel
    assert "JSON.stringify" not in source


def test_workbench_one_sentence_agent_entry() -> None:
    panel = (COMPONENTS / "project-prompt-panel.tsx").read_text(encoding="utf-8")
    page = (WORKBENCH / "page.tsx").read_text(encoding="utf-8")
    hook = (HOOKS / "use-workbench.ts").read_text(encoding="utf-8")

    assert "一句话 Prompt" in panel
    assert "生成科研动画" in panel
    assert "自动推断" in panel
    assert "科学与技术动画工作台" in page
    assert "ContentPlan · IntentSpec · Tools · Compiler · Sandbox" in page
    assert "教学动画路径（ContentPlan）" in panel
    assert "runAgent" in hook
    source = (HOOKS / "use-render-monitor.ts").read_text(encoding="utf-8")

    assert "new EventSource" in source
    assert "withCredentials: true" in source
    assert "lastEventId" in source
    assert "workbenchApi.getRenderJob" in source


def test_web_build_uses_only_local_system_font_stacks() -> None:
    layout = (WEB / "app/layout.tsx").read_text(encoding="utf-8")
    styles = (WEB / "app/styles.css").read_text(encoding="utf-8")
    source = _sources(WEB)

    assert "next/font/google" not in source
    assert "fonts.googleapis.com" not in source
    assert "fonts.gstatic.com" not in source
    for variable in ("--font-display", "--font-body", "--font-script", "--font-mono", "--font-cjk"):
        assert variable in styles
    assert "next/font" not in layout


def test_next_build_uses_compiler_api_instead_of_broken_cli_capture() -> None:
    config = (ROOT / "apps/web/next.config.ts").read_text(encoding="utf-8")

    assert "useTypeScriptCli: false" in config
