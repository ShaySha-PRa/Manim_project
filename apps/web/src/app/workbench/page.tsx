"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { ContentPlanEditor } from "../../components/workbench/content-plan-editor";
import { ProjectPromptPanel } from "../../components/workbench/project-prompt-panel";
import { RenderPanel } from "../../components/workbench/render-panel";
import { useWorkbenchSession } from "../../hooks/workbench/use-workbench-session";
import { useWorkbench } from "../../hooks/workbench/use-workbench";
import { workbenchApi } from "../../lib/api/client";

import styles from "./workbench.module.css";

export default function WorkbenchPage() {
  const router = useRouter();
  const session = useWorkbenchSession();
  const model = useWorkbench();
  const { loadProjects, recoverRenderJob } = model;

  useEffect(() => {
    if (session.state !== "ready") return;
    void loadProjects();
    void recoverRenderJob();
  }, [session.state, loadProjects, recoverRenderJob]);

  if (session.state === "loading") {
    return <main className={styles.loading} aria-live="polite">正在恢复安全会话…</main>;
  }
  if (session.state === "error") {
    return <main className={styles.loading} role="alert"><p>{session.error}</p><button onClick={() => void session.recover()}>重试</button></main>;
  }

  return (
    <main className={styles.workbench} id="main-content">
      <header className={styles.header}>
        <div><p className={styles.eyebrow}>MANIM WORKBENCH</p><h1>数学动画工作台</h1></div>
        <div>
          <p>已登录：{session.user?.email}</p>
          <button type="button" onClick={() => void workbenchApi.logout().then(() => router.replace("/login")).catch(() => model.setMessage("退出失败，请稍后重试。"))}>退出登录</button>
        </div>
      </header>
      {model.busy && <p className={styles.progress} aria-live="polite">正在处理请求，请勿关闭此页面…</p>}
      {model.message && <div className={styles.notice} role="status"><span>{model.message}</span><button type="button" aria-label="关闭提示" onClick={() => model.setMessage(null)}>关闭</button></div>}
      <div className={styles.grid}>
        <ProjectPromptPanel model={model} />
        <ContentPlanEditor model={model} />
        <RenderPanel model={model} />
      </div>
    </main>
  );
}
