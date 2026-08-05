import type { PipelineStage, QualityDiagnostic, QualityReport, QualitySeverity, QualityStatus } from "@manim-workbench/contracts";

const stageLabels: Record<PipelineStage, string> = {
  prompt: "Prompt",
  content_plan: "ContentPlan",
  code_generation: "代码生成",
  preview_render: "预览渲染",
  final_render: "终渲渲染",
  artifact_delivery: "产物交付",
  quality_analysis: "质量分析",
  quality_recovery: "质量修复",
};

const statusLabels: Record<QualityStatus, string> = {
  pending: "等待质量检查",
  analyzing: "正在质量分析",
  repair_required: "需要修复",
  repairing: "正在修复",
  passed: "质量通过",
  degraded: "已降级交付",
  failed: "质量检查未通过",
};

const severityLabels: Record<QualitySeverity, string> = {
  info: "提示",
  warning: "注意",
  error: "需要处理",
};

const sensitiveText = [
  /(?:api[_-]?key|authorization|cookie|csrf|password|secret|session|token)\s*[:=]\s*\S+/i,
  /\bsk-[A-Za-z0-9_-]{8,}\b/,
  /(?:^|\s)(?:[a-z]:[\\/]|\/(?:home|root|etc|var|tmp)\/)/i,
  /(?:traceback|stack trace|from\s+manim\s+import|class\s+\w*scene|def\s+construct\b)/i,
];

export type PresentedDiagnostic = {
  readonly id: string;
  readonly severity: string;
  readonly stage: string;
  readonly message: string;
  readonly suggestion: string;
};

export function redactQualityText(value: string | null | undefined, fallback: string): string {
  const normalized = value?.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim();
  if (!normalized || normalized.length > 300 || sensitiveText.some((pattern) => pattern.test(normalized))) {
    return fallback;
  }
  return normalized;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) {
    return "等待诊断";
  }
  return `${seconds.toFixed(1)} 秒`;
}

export function formatScore(score: number | null | undefined): string {
  if (score === null || score === undefined || !Number.isFinite(score)) return "未评分";
  return `${Math.max(0, Math.min(100, score)).toFixed(0)} / 100`;
}

export function statusLabel(status: QualityStatus): string {
  return statusLabels[status];
}

export function presentDiagnostics(diagnostics: ReadonlyArray<QualityDiagnostic>): ReadonlyArray<PresentedDiagnostic> {
  return diagnostics.map((diagnostic, index) => ({
    id: `${diagnostic.code}-${diagnostic.stage}-${index}`,
    severity: severityLabels[diagnostic.severity],
    stage: stageLabels[diagnostic.stage],
    message: redactQualityText(diagnostic.message, "系统已记录该质量问题。"),
    suggestion: redactQualityText(diagnostic.suggestion, "请根据该问题重新检查相应教学步骤。"),
  }));
}

export function primaryPipelineStage(diagnostics: ReadonlyArray<QualityDiagnostic>): string {
  return diagnostics[0] ? stageLabels[diagnostics[0].stage] : "等待诊断";
}

export function degradationReason(
  report: QualityReport,
  diagnostics: ReadonlyArray<QualityDiagnostic>,
): string {
  if (report.status !== "degraded") return "未降级";
  const primary = diagnostics.find((diagnostic) => diagnostic.severity !== "info");
  return primary
    ? redactQualityText(primary.message, "系统因质量检查结果进行了受限交付。")
    : "系统因质量检查结果进行了受限交付。";
}
