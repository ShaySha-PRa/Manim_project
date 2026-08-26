import { useState } from "react";

import type { RenderProfile, SceneBlockRun, SceneDraft } from "./types";
import { ScenePreview } from "./scene-preview";

import styles from "../../app/workflows/workflows.module.css";

type Props = {
  index: number;
  scene: SceneDraft;
  previewRun?: SceneBlockRun;
  finalRun?: SceneBlockRun;
  count: number;
  onUpdate: (patch: Partial<SceneDraft>) => void;
  onGenerate: (profile: RenderProfile) => void;
  onUploadCsv: (csvText: string) => void;
  onMove: (delta: -1 | 1) => void;
  onCopy: () => void;
  onRemove: () => void;
  onDragStart: () => void;
  onDrop: () => void;
};

export function SceneBlockCard(props: Props) {
  const { scene, previewRun, finalRun } = props;
  const evidenceRun = finalRun ?? previewRun;
  const [csvText, setCsvText] = useState("");
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
          <details><summary>补充 CSV 资产</summary><label>CSV 内容<textarea rows={4} value={csvText} onChange={(event) => setCsvText(event.target.value)} placeholder="timestamp,temperature,pressure" /></label><button type="button" disabled={!csvText.trim()} onClick={() => props.onUploadCsv(csvText)}>保存并绑定 AssetVersion</button></details>
          <div className={styles.actions}><button type="button" onClick={() => props.onGenerate("preview")} disabled={!scene.version}>生成 Preview</button><button type="button" onClick={() => props.onGenerate("final")} disabled={!scene.version}>生成 Final</button></div>
          {evidenceRun?.error_code && <p className={styles.error} role="alert">失败原因：{evidenceRun.error_code}</p>}
          <p>Preview：{previewRun?.status ?? "尚未生成"} · Final：{finalRun?.status ?? "尚未生成"}</p>
          {evidenceRun && <details><summary>数据来源与执行证据</summary><dl className={styles.provenance}><dt>路径</dt><dd>{evidenceRun.pipeline_used ?? "待确认"}</dd><dt>IntentSpec</dt><dd>{evidenceRun.intent_ref ?? "—"}</dd><dt>AnimationIR</dt><dd>{evidenceRun.animation_ir_ref ?? "—"}</dd><dt>CompiledProgram</dt><dd>{evidenceRun.compiled_program_ref ?? "—"}</dd><dt>Cache</dt><dd>{evidenceRun.cache_key || "—"}</dd></dl></details>}
        </div>
        <div className={styles.preview}><ScenePreview run={previewRun} /></div>
      </div>
    </article>
  );
}
