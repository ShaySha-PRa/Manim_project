"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { AuthShell } from "../../components/auth/auth-shell";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { StatusMessage } from "../../components/ui/status-message";
import { workbenchApi } from "../../lib/api/client";

const LOGIN_FAILED_MESSAGE = "邮箱或密码不正确，或当前暂时无法登录。请检查后重试。";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting) return;

    setError(null);
    setIsSubmitting(true);
    try {
      const session = await workbenchApi.login({ email: email.trim(), password });
      router.replace(session.user.must_change_password ? "/change-password" : "/workbench");
    } catch {
      setError(LOGIN_FAILED_MESSAGE);
      setIsSubmitting(false);
    }
  }

  return (
    <AuthShell
      description="使用管理员为你创建的账号登录。首次登录后，需要立即设置仅自己掌握的新密码。"
      eyebrow="账户登录"
      footer="此工作台不在浏览器保存登录令牌；浏览器仅持有受保护的会话 Cookie。"
      title="进入工作台"
    >
      <form className="auth-form" onSubmit={handleSubmit}>
        <div className="form-field">
          <label htmlFor="email">邮箱</label>
          <Input
            autoComplete="username"
            autoFocus
            id="email"
            inputMode="email"
            name="email"
            onChange={(event) => setEmail(event.target.value)}
            required
            type="email"
            value={email}
          />
        </div>
        <div className="form-field">
          <label htmlFor="password">密码</label>
          <Input
            autoComplete="current-password"
            id="password"
            name="password"
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
        </div>
        {error ? <StatusMessage tone="error">{error}</StatusMessage> : null}
        <Button disabled={isSubmitting} fullWidth type="submit">
          {isSubmitting ? "正在验证…" : "登录"}
        </Button>
      </form>
    </AuthShell>
  );
}
