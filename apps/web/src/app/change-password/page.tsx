"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { AuthShell } from "../../components/auth/auth-shell";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { StatusMessage } from "../../components/ui/status-message";
import { ApiClientError, workbenchApi } from "../../lib/api/client";

const PASSWORD_CHANGE_FAILED_MESSAGE = "无法更新密码。请确认当前密码后重试。";
const SESSION_CHECK_FAILED_MESSAGE = "暂时无法确认会话。请稍后重试。";

type PageState = "checking" | "ready" | "error";

export default function ChangePasswordPage() {
  const router = useRouter();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [pageState, setPageState] = useState<PageState>("checking");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let active = true;

    async function restoreSession() {
      try {
        const session = await workbenchApi.session();
        if (!session.user.must_change_password) {
          router.replace("/workbench");
          return;
        }
        if (active) setPageState("ready");
      } catch (requestError) {
        if (!active) return;
        if (requestError instanceof ApiClientError && [401, 403].includes(requestError.status)) {
          router.replace("/login");
          return;
        }
        setError(SESSION_CHECK_FAILED_MESSAGE);
        setPageState("error");
      }
    }

    void restoreSession();
    return () => {
      active = false;
    };
  }, [router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting || pageState !== "ready") return;

    setError(null);
    setIsSubmitting(true);
    try {
      await workbenchApi.changePassword({ current_password: currentPassword, new_password: newPassword });
      router.replace("/workbench");
    } catch {
      setError(PASSWORD_CHANGE_FAILED_MESSAGE);
      setIsSubmitting(false);
    }
  }

  return (
    <AuthShell
      description="这是账户的首次安全设置。完成后，系统会撤销旧会话，并为当前浏览器建立新会话。"
      eyebrow="首次安全设置"
      footer="新密码不会被浏览器保存；请使用只有你自己掌握的密码。"
      title="设置新密码"
    >
      {pageState === "checking" ? (
        <StatusMessage>正在确认受保护会话…</StatusMessage>
      ) : null}
      {pageState === "error" ? (
        <div className="auth-form">
          {error ? <StatusMessage tone="error">{error}</StatusMessage> : null}
          <Button fullWidth onClick={() => window.location.reload()} variant="secondary">
            重新检查会话
          </Button>
        </div>
      ) : null}
      {pageState === "ready" ? (
        <form className="auth-form" onSubmit={handleSubmit}>
          <div className="form-field">
            <label htmlFor="current-password">当前密码</label>
            <Input
              autoComplete="current-password"
              autoFocus
              id="current-password"
              name="current-password"
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
              type="password"
              value={currentPassword}
            />
          </div>
          <div className="form-field">
            <label htmlFor="new-password">新密码</label>
            <Input
              aria-describedby="new-password-help"
              autoComplete="new-password"
              id="new-password"
              name="new-password"
              onChange={(event) => setNewPassword(event.target.value)}
              required
              type="password"
              value={newPassword}
            />
            <p className="form-help" id="new-password-help">
              请使用长度充足、仅你自己掌握的密码。
            </p>
          </div>
          {error ? <StatusMessage tone="error">{error}</StatusMessage> : null}
          <Button disabled={isSubmitting} fullWidth type="submit">
            {isSubmitting ? "正在更新…" : "完成并进入工作台"}
          </Button>
        </form>
      ) : null}
    </AuthShell>
  );
}
