import { CompositionPanel } from "./composition-panel";
import { DirectorPanel } from "./director-panel";
import { GlobalBriefPanel } from "./global-brief-panel";
import { SceneBlockList } from "./scene-block-list";
import { WorkflowStatus } from "./workflow-status";
import { useVideoWorkflow } from "../../hooks/workflow/use-video-workflow";

import styles from "../../app/workflows/workflows.module.css";

export type ReturnTypeVideoWorkflow = ReturnType<typeof useVideoWorkflow>;

export function WorkflowEditor({ enabled }: { enabled: boolean }) {
  const model = useVideoWorkflow(enabled);
  return <>
    <header className={styles.hero}><div><p className={styles.eyebrow}>COMPOSABLE SCENE WORKFLOW</p><h1>把自然语言场景组合成完整视频</h1><p>每一幕独立生成、缓存和预览；修改一幕只重跑这一幕与最终合成。</p></div><div className={styles.saveBox}><label>项目<select value={model.projectId} onChange={(event) => model.setProjectId(event.target.value)}>{model.projects.map((project) => <option key={project.id} value={project.id}>{project.title}</option>)}</select></label><button type="button" onClick={() => void model.persist()} disabled={model.busy}>保存新版本</button></div></header>
    <WorkflowStatus model={model} />
    {model.message && <div className={styles.notice} role="status"><span>{model.message}</span><button type="button" onClick={() => model.setMessage(null)} aria-label="关闭提示">关闭</button></div>}
    <DirectorPanel model={model} />
    <GlobalBriefPanel brief={model.brief} onChange={model.setBrief} />
    <SceneBlockList model={model} />
    <CompositionPanel model={model} />
  </>;
}
