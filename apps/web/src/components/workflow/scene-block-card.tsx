import type { RenderProfile, SceneBlockRun, SceneDraft } from "./types";
import { ScenePreview } from "./scene-preview";

import styles from "../../app/workflows/workflows.module.css";

type Props = {
  index: number;
  scene: SceneDraft;
  run?: SceneBlockRun;
  count: number;
  onUpdate: (patch: Partial<SceneDraft>) => void;
  onGenerate: (profile: RenderProfile) => void;
  onMove: (delta: -1 | 1) => void;
  onCopy: () => void;
  onRemove: () => void;
  onDragStart: () => void;
  onDrop: () => void;
};

export function SceneBlockCard(props: Props) {
  const { scene, run } = props;
  return (
    <article className={styles.sceneCard} draggable onDragStart={props.onDragStart} onDragOver={(event) => event.preventDefault()} onDrop={props.onDrop}>
      <div className={styles.sceneHeader}>
        <div><span className={styles.sceneNumber}>{String(props.index + 1).padStart(2, "0")}</span><strong>{scene.title || "未命名场景"}</strong>{scene.dirty && <span className={styles.unsaved}>未保存</span>}</div>
        <div className={styles.iconActions}><button type="button" onClick={() => props.onMove(-1)} disabled={props.index === 0} aria-label="上移场景">↑</button><button type="button" onClick={() => props.onMove(1)} disabled={props.index === props.count - 1} aria-label="下移场景">↓</button><button type="button" onClick={props.onCopy}>复制</button><button type="button" onClick={props.onRemove} disabled={scene.blockId !== null}>删除草稿</button></div>
      </div>
      <div className={styles.sceneBody}>
        <div className={styles.editor}>
          <label>标题<input value={scene.title} onChange={(event) => props.onUpdate({ title: event.target.value })} /></label>
          <label>自然语言场景描述<textarea rows={5} value={scene.prompt} onChange={(event) => props.onUpdate({ prompt: event.target.value })} placeholder="描述这一幕要解释、计算并展示什么…" /></label>
          <div className={styles.formGrid}>
            <label>生成路径<select value={scene.pipelineMode} onChange={(event) => props.onUpdate({ pipelineMode: event.target.value as SceneDraft["pipelineMode"] })}><option value="auto">自动（不确定时询问）</option><option value="teaching">教学</option><option value="scientific">科研</option></select></label>
            <label>目标时长（秒）<input type="number" min={15} max={120} value={scene.targetDurationSeconds} onChange={(event) => props.onUpdate({ targetDurationSeconds: Number(event.target.value) })} /></label>
          </div>
          <label>AssetVersion ID（每行一个）<textarea rows={2} value={scene.assetVersionIds.join("\n")} onChange={(event) => props.onUpdate({ assetVersionIds: event.target.value.split(/\s+/).filter(Boolean) })} placeholder="需要 CSV 时绑定真实 AssetVersion" /></label>
          <div className={styles.actions}><button type="button" onClick={() => props.onGenerate("preview")} disabled={!scene.version}>生成 Preview</button><button type="button" onClick={() => props.onGenerate("final")} disabled={!scene.version}>生成 Final</button></div>
          {run?.error_code && <p className={styles.error} role="alert">失败原因：{run.error_code}</p>}
          {run && <details><summary>数据来源与执行证据</summary><dl className={styles.provenance}><dt>路径</dt><dd>{run.pipeline_used ?? "待确认"}</dd><dt>IntentSpec</dt><dd>{run.intent_ref ?? "—"}</dd><dt>AnimationIR</dt><dd>{run.animation_ir_ref ?? "—"}</dd><dt>CompiledProgram</dt><dd>{run.compiled_program_ref ?? "—"}</dd><dt>Cache</dt><dd>{run.cache_key || "—"}</dd></dl></details>}
        </div>
        <div className={styles.preview}><ScenePreview run={run} /></div>
      </div>
    </article>
  );
}
