from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
QUALITY = ROOT / "apps/web/src/components/quality"
HOOKS = ROOT / "apps/web/src/hooks/quality"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_quality_panel_exposes_the_frozen_quality_summary_semantically() -> None:
    source = _source(QUALITY / "quality-panel.tsx")

    assert '"use client"' in source
    assert "export function QualityPanel" in source
    assert '<section aria-labelledby="quality-heading"' in source
    assert '<dl aria-label="质量指标"' in source
    for label in ("目标时长", "估算时长", "实际时长", "质量评分", "修复次数"):
        assert label in source
    assert "诊断项" in source
    assert "管线阶段" in source
    assert "降级原因" in source
    assert "修改建议" in source


def test_quality_panel_has_loading_empty_error_and_live_status_states() -> None:
    source = _source(QUALITY / "quality-panel.tsx")

    assert 'aria-live="polite"' in source
    assert 'state === "loading"' in source
    assert 'state === "empty"' in source
    assert 'state === "error"' in source
    assert "正在分析视频质量" in source
    assert "尚未生成质量报告" in source
    assert "暂时无法读取质量报告" in source


def test_quality_panel_uses_native_keyboard_controls_and_safe_text_only_output() -> None:
    source = _source(QUALITY / "quality-panel.tsx")
    presentation = _source(QUALITY / "quality-presentation.ts")
    combined = "\n".join((source, presentation))

    assert "<button" in source
    assert "aria-expanded" in source
    assert "aria-controls" in source
    assert "dangerouslySetInnerHTML" not in combined
    assert "<pre" not in source
    assert "<code" not in source
    assert "evidence_ref" not in combined
    assert "owner_id" not in combined
    assert "JSON.stringify" not in combined
    assert "localStorage" not in combined
    assert "sessionStorage" not in combined
    assert "Authorization" not in combined
    assert "redactQualityText" in source


def test_quality_hook_uses_parent_client_and_treats_unavailable_report_as_empty() -> None:
    source = _source(HOOKS / "use-quality-report.ts")
    panel = _source(QUALITY / "quality-panel.tsx")

    assert "workbenchApi.getJobQualityReport" in source
    assert "workbenchApi.listQualityDiagnostics" in source
    assert "ApiClientError" in source
    assert "cause.status === 404" in source
    assert "refresh" in source
    assert "AbortController" in source
    assert "refreshKey" in source
    assert "refreshKey" in panel
    assert (
        "const nextReport = await workbenchApi.getJobQualityReport(jobId);\n"
        "      if (signal?.aborted) return;\n"
        "      const nextDiagnostics = await workbenchApi.listQualityDiagnostics(nextReport.id);"
    ) in source


def test_parent_workbench_connects_quality_to_the_active_job_state() -> None:
    source = _source(ROOT / "apps/web/src/components/workbench/render-panel.tsx")

    assert 'import { QualityPanel } from "../quality/quality-panel"' in source
    assert "jobId={job && terminal.has(job.status) ? job.id : null}" in source
    assert "refreshKey={job?.state_version}" in source
