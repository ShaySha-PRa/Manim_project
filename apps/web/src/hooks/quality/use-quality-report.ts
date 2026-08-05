"use client";

import { useCallback, useEffect, useState } from "react";

import type { QualityDiagnostic, QualityReport } from "@manim-workbench/contracts";

import { ApiClientError, workbenchApi } from "../../lib/api/client";

export type QualityReportLoadState = "loading" | "empty" | "ready" | "error";

export type QualityReportModel = {
  readonly state: QualityReportLoadState;
  readonly report: QualityReport | null;
  readonly diagnostics: ReadonlyArray<QualityDiagnostic>;
  readonly error: string | null;
  readonly refresh: () => void;
};

const unavailableReport = (cause: unknown) => cause instanceof ApiClientError && cause.status === 404;

export function useQualityReport(
  jobId: string | null | undefined,
  refreshKey?: string | number | null,
): QualityReportModel {
  const [state, setState] = useState<QualityReportLoadState>("empty");
  const [report, setReport] = useState<QualityReport | null>(null);
  const [diagnostics, setDiagnostics] = useState<ReadonlyArray<QualityDiagnostic>>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (!jobId) {
      if (!signal?.aborted) {
        setState("empty");
        setReport(null);
        setDiagnostics([]);
        setError(null);
      }
      return;
    }

    setState("loading");
    setError(null);
    try {
      const nextReport = await workbenchApi.getJobQualityReport(jobId);
      if (signal?.aborted) return;
      const nextDiagnostics = await workbenchApi.listQualityDiagnostics(nextReport.id);
      if (signal?.aborted) return;
      setReport(nextReport);
      setDiagnostics(nextDiagnostics);
      setState("ready");
    } catch (cause) {
      if (signal?.aborted) return;
      setReport(null);
      setDiagnostics([]);
      if (unavailableReport(cause)) {
        setState("empty");
        setError(null);
        return;
      }
      setState("error");
      setError("质量报告暂时不可用，请稍后重试。");
    }
  }, [jobId]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void load(controller.signal);
    }, 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [load, refreshKey]);

  const refresh = useCallback(() => {
    void load();
  }, [load]);

  return { state, report, diagnostics, error, refresh };
}
