"use client";

import { useId, useState } from "react";

import type { QualityDiagnostic, QualityReport } from "@manim-workbench/contracts";

import { useQualityReport } from "../../hooks/quality/use-quality-report";

import {
  degradationReason,
  formatDuration,
  formatScore,
  presentDiagnostics,
  primaryPipelineStage,
  redactQualityText,
  statusLabel,
} from "./quality-presentation";
import styles from "./quality-panel.module.css";

type QualityPanelProps = {
  readonly jobId: string | null | undefined;
  readonly refreshKey?: string | number | null;
};

function Metric({ label, value }: Readonly<{ label: string; value: string }>) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function ReportDetails({
  report,
  diagnostics,
}: Readonly<{ report: QualityReport; diagnostics: ReadonlyArray<QualityDiagnostic> }>) {
  const [expanded, setExpanded] = useState(false);
  const diagnosticId = useId();
  const presentedDiagnostics = presentDiagnostics(diagnostics);
  const visibleDiagnostics = expanded ? presentedDiagnostics : presentedDiagnostics.slice(0, 3);
  const hasHiddenDiagnostics = presentedDiagnostics.length > visibleDiagnostics.length;

  return (
    <>
      <p className={styles.statusLine} aria-live="polite" aria-atomic="true">
        状态：<strong>{statusLabel(report.status)}</strong> · 管线阶段：{primaryPipelineStage(diagnostics)}
      </p>
      <dl aria-label="质量指标" className={styles.metrics}>
        <Metric label="目标时长" value={formatDuration(report.target_duration_seconds)} />
        <Metric label="估算时长" value={formatDuration(report.estimated_duration_seconds)} />
        <Metric label="实际时长" value={formatDuration(report.actual_duration_seconds)} />
        <Metric label="质量评分" value={formatScore(report.score)} />
        <Metric label="修复次数" value={`${report.repair_count} 次`} />
        <Metric label="降级原因" value={degradationReason(report, diagnostics)} />
      </dl>
      <section aria-labelledby={`${diagnosticId}-heading`}>
        <h4 id={`${diagnosticId}-heading`}>诊断项</h4>
        {!presentedDiagnostics.length && <p className={styles.empty}>当前没有需要修改的诊断项。</p>}
        {!!presentedDiagnostics.length && (
          <>
            <ul className={styles.diagnostics} id={diagnosticId} role="list">
              {visibleDiagnostics.map((diagnostic) => (
                <li className={styles.diagnostic} key={diagnostic.id}>
                  <p className={styles.diagnosticMeta}><strong>{diagnostic.severity}</strong> · {diagnostic.stage}</p>
                  <p className={styles.diagnosticMessage}>{diagnostic.message}</p>
                  <p className={styles.diagnosticSuggestion}><strong>修改建议：</strong>{diagnostic.suggestion}</p>
                </li>
              ))}
            </ul>
            {(hasHiddenDiagnostics || expanded) && (
              <div className={styles.actions}>
                <button
                  aria-controls={diagnosticId}
                  aria-expanded={expanded}
                  onClick={() => setExpanded((current) => !current)}
                  type="button"
                >
                  {expanded ? "收起诊断项" : `查看全部 ${presentedDiagnostics.length} 项诊断`}
                </button>
              </div>
            )}
          </>
        )}
      </section>
    </>
  );
}

export function QualityPanel({ jobId, refreshKey }: Readonly<QualityPanelProps>) {
  const { state, report, diagnostics, error, refresh } = useQualityReport(jobId, refreshKey);

  return (
    <section aria-labelledby="quality-heading" aria-busy={state === "loading"} className={styles.panel}>
      <h3 className={styles.heading} id="quality-heading">质量诊断</h3>
      {state === "loading" && <p className={styles.statusLine} aria-live="polite">正在分析视频质量…</p>}
      {state === "empty" && <p className={styles.empty} aria-live="polite">尚未生成质量报告。渲染完成后会自动显示时长和画面检查结果。</p>}
      {state === "error" && (
        <>
          <p className={styles.error} role="alert">暂时无法读取质量报告。</p>
          {error && <p className={styles.empty}>{redactQualityText(error, "请稍后重试。")}</p>}
          <div className={styles.actions}><button onClick={refresh} type="button">重试读取</button></div>
        </>
      )}
      {state === "ready" && report && <ReportDetails diagnostics={diagnostics} report={report} />}
    </section>
  );
}
