import type { ReturnTypeVideoWorkflow } from "./workflow-editor";

import styles from "../../app/workflows/workflows.module.css";

export function WorkflowStatus({ model }: { model: ReturnTypeVideoWorkflow }) {
  return <div className={styles.statusBar}><span>{model.version ? `Workflow v${model.version.version}` : "新工作流"}</span><span>{model.scenes.length} 个场景</span><span>{model.scenes.reduce((total, scene) => total + scene.targetDurationSeconds, 0)} 秒目标时长</span>{model.busy && <span aria-live="polite">正在保存…</span>}</div>;
}
