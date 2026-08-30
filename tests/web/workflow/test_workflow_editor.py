from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "apps/web/src"
WORKFLOWS = WEB / "app/workflows"
COMPONENTS = WEB / "components/workflow"
HOOKS = WEB / "hooks/workflow"


def _sources(*roots: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for root in roots for path in sorted(root.rglob("*.ts*"))
    )


def test_workflow_route_recovers_authoritative_version_and_runs_from_url() -> None:
    page = (WORKFLOWS / "page.tsx").read_text(encoding="utf-8")
    hook = (HOOKS / "use-video-workflow.ts").read_text(encoding="utf-8")

    assert '"use client"' in page
    assert "useWorkbenchSession" in page
    assert 'query.get("version")' in hook
    assert 'query.get("runs")' in hook
    assert 'query.get("composition")' in hook
    assert "getVideoWorkflowVersion" in hook
    assert "getSceneBlockRun" in hook
    assert "getCompositionRun" in hook
    assert "setInterval" in hook
    assert "submissions.current.has" in hook
    assert "retainRunsForCurrentScenes(runs, persisted)" in hook
    assert "updateUrl(nextVersion, retainedRuns, null)" in hook


def test_linear_editor_has_accessible_reorder_and_no_free_canvas() -> None:
    source = _sources(WORKFLOWS, COMPONENTS, HOOKS)
    card = (COMPONENTS / "scene-block-card.tsx").read_text(encoding="utf-8")

    assert "draggable" in card
    assert 'aria-label="上移场景"' in card
    assert 'aria-label="下移场景"' in card
    assert "添加场景" in source
    assert "删除草稿" in source
    assert "复制" in source
    assert "reactflow" not in source.lower()
    assert "ReactFlow" not in source


def test_scene_cards_expose_generation_safe_stops_and_provenance() -> None:
    source = _sources(COMPONENTS, HOOKS)

    assert "生成 Preview" in source
    assert "生成 Final" in source
    assert "asset_required" in source
    assert "needs_confirmation" in source
    assert "不会生成占位视频" in source
    assert "IntentSpec" in source
    assert "AnimationIR" in source
    assert "CompiledProgram" in source
    assert "AssetVersion" in source
    assert "保存并绑定 AssetVersion" in source
    assert "createScientificCsvAsset" in source


def test_composition_is_blocked_until_all_current_scenes_succeed() -> None:
    panel = (COMPONENTS / "composition-panel.tsx").read_text(encoding="utf-8")
    hook = (HOOKS / "use-video-workflow.ts").read_text(encoding="utf-8")

    assert "allSucceeded" in panel
    assert "尚不能合成" in panel
    assert "Composition Manifest" in panel
    assert "下载完整 MP4" in panel
    assert 'allSucceeded("preview")' in panel
    assert 'allSucceeded("final")' in panel
    assert "sceneRunKey(scene.version.id, profile)" in hook
    assert 'run.profile' in hook


def test_browser_state_does_not_store_owner_tokens_or_authorization_headers() -> None:
    source = _sources(WORKFLOWS, COMPONENTS, HOOKS)

    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "Authorization" not in source


def test_browser_gate_starts_the_configured_standalone_server() -> None:
    config = (ROOT / "tests/web/workflow/workflow.playwright.config.ts").read_text(
        encoding="utf-8"
    )

    assert ".next/standalone/apps/web/server.js" in config
    assert "run start" not in config
