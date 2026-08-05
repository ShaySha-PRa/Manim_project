"use client";

import { useEffect, useRef } from "react";

import type { JobEvent, RenderJob } from "@manim-workbench/contracts";

import { workbenchApi } from "../../lib/api/client";

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

export function useRenderMonitor(
  jobId: string | null,
  onJob: (job: RenderJob) => void,
  onError: (message: string) => void,
) {
  const lastEventId = useRef("0");

  useEffect(() => {
    if (!jobId) return;
    let disposed = false;
    let stream: EventSource | null = null;

    const refresh = async () => {
      try {
        const job = await workbenchApi.getRenderJob(jobId);
        if (!disposed) {
          onJob(job);
          if (TERMINAL.has(job.status)) stream?.close();
        }
      } catch {
        if (!disposed) onError("任务状态暂时不可用，将继续尝试恢复。");
      }
    };

    const start = () => {
      stream = new EventSource(workbenchApi.eventUrl(jobId), { withCredentials: true });
      stream.addEventListener("render_job", (event) => {
        const message = event as MessageEvent<string>;
        const payload = JSON.parse(message.data) as JobEvent;
        lastEventId.current = message.lastEventId || String(payload.event_id);
        void refresh();
      });
      stream.onerror = () => {
        // The browser reconnects with Last-Event-ID for this same EventSource.
        void refresh();
      };
    };

    void refresh();
    start();
    const polling = window.setInterval(() => void refresh(), 5_000);
    return () => {
      disposed = true;
      window.clearInterval(polling);
      stream?.close();
    };
  }, [jobId, onError, onJob]);
}
