"use client";

import { WorkflowEditor } from "../../components/workflow/workflow-editor";
import { useWorkbenchSession } from "../../hooks/workbench/use-workbench-session";

import styles from "./workflows.module.css";

export default function WorkflowsPage() {
  const session = useWorkbenchSession();
  if (session.state === "loading") return <main className={styles.loading} aria-live="polite">正在恢复安全会话…</main>;
  if (session.state === "error") return <main className={styles.loading} role="alert"><p>{session.error}</p><button type="button" onClick={() => void session.recover()}>重试</button></main>;
  return <main className={styles.workflows} id="main-content"><WorkflowEditor enabled /></main>;
}
