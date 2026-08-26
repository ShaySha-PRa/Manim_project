import { useState } from "react";

import type { ReturnTypeVideoWorkflow } from "./workflow-editor";
import { SceneBlockCard } from "./scene-block-card";

import styles from "../../app/workflows/workflows.module.css";

export function SceneBlockList({ model }: { model: ReturnTypeVideoWorkflow }) {
  const [dragged, setDragged] = useState<number | null>(null);
  return (
    <section aria-labelledby="scene-list-title">
      <div className={styles.listHeading}><div><p className={styles.eyebrow}>SCENE BLOCKS</p><h2 id="scene-list-title">场景积木</h2></div><button type="button" onClick={model.addScene} disabled={model.scenes.length >= 8}>＋ 添加场景</button></div>
      <p className={styles.hint}>拖动或使用上移/下移调整顺序。已保存版本不会原地覆盖。</p>
      <div className={styles.sceneList}>
        {model.scenes.map((scene, index) => { const previewRun = model.runFor(scene, "preview"); const finalRun = model.runFor(scene, "final"); const evidenceRun = finalRun ?? previewRun; return <SceneBlockCard key={scene.localId} index={index} count={model.scenes.length} scene={scene} previewRun={previewRun} finalRun={finalRun} provenance={evidenceRun ? model.provenance[evidenceRun.id] : undefined} onUpdate={(patch) => model.updateScene(scene.localId, patch)} onGenerate={(profile) => void model.generateScene(scene, profile)} onLoadProvenance={() => evidenceRun && void model.loadProvenance(evidenceRun)} onUploadCsv={(csvText) => void model.uploadCsv(scene, csvText)} onMove={(delta) => model.moveScene(index, delta)} onCopy={() => model.copyScene(scene)} onRemove={() => model.removeDraft(scene.localId)} onDragStart={() => setDragged(index)} onDrop={() => { if (dragged !== null) model.reorderScene(dragged, index); setDragged(null); }} />; })}
      </div>
    </section>
  );
}
