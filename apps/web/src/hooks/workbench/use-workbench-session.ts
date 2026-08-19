"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import type { AuthenticatedUser } from "@manim-workbench/contracts";

import { ApiClientError, workbenchApi } from "../../lib/api/client";

export type SessionState = "loading" | "ready" | "error";

export function useWorkbenchSession() {
  const router = useRouter();
  const [state, setState] = useState<SessionState>("loading");
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [error, setError] = useState<string | null>(null);

  const recover = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      const session = await workbenchApi.session();
      setUser(session.user);
      setState("ready");
    } catch (cause) {
      if (cause instanceof ApiClientError && cause.status === 401) {
        router.replace("/login");
        return;
      }
      setError("无法恢复会话。请检查服务后重试。");
      setState("error");
    }
  }, [router]);

  useEffect(() => {
    const timer = window.setTimeout(() => void recover(), 0);
    return () => window.clearTimeout(timer);
  }, [recover]);

  return { state, user, error, recover };
}
