import { workbenchApi } from "../../lib/api/client";
import type { ReturnTypeVideoWorkflow } from "./workflow-editor";

import styles from "../../app/workflows/workflows.module.css";

export function CompositionPanel({ model }: { model: ReturnTypeVideoWorkflow }) {
  const blockers = model.scenes.filter((scene) => !scene.version || model.runs[scene.version.id]?.status !== "succeeded");
  const run = model.composition;
  const artifactUrl = run?.status === "succeeded" ? workbenchApi.compositionArtifactUrl(run.id) : null;
  return (
    <section className={styles.panel} aria-labelledby="composition-title">
      <div className={styles.panelHeading}><div><p className={styles.eyebrow}>COMPOSE &amp; EXPORT</p><h2 id="composition-title">完整视频</h2></div>{run && <span className={styles.badge}>{run.status}</span>}</div>
      <div className={styles.actions}><button type="button" onClick={() => void model.generateIncomplete("preview")}>生成所有未完成 Preview</button><button type="button" onClick={() => void model.generateIncomplete("final")}>生成所有未完成 Final</button><button type="button" disabled={!model.allSucceeded} onClick={() => void model.compose("preview")}>合成整片 Preview</button><button type="button" disabled={!model.allSucceeded} onClick={() => void model.compose("final")}>生成整片 Final</button></div>
      {blockers.length > 0 && <div className={styles.blockers}><strong>尚不能合成</strong><ul>{blockers.map((scene) => <li key={scene.localId}>{scene.title}: {scene.version ? model.runs[scene.version.id]?.status ?? "尚未生成" : "尚未保存"}</li>)}</ul></div>}
      {artifactUrl && <div className={styles.finalVideo}><video className={styles.video} controls preload="metadata" src={artifactUrl} /><a className={styles.download} href={artifactUrl}>下载完整 MP4</a></div>}
      {run?.manifest && <details><summary>Composition Manifest</summary><p>{run.manifest.clips.length} 个场景 · {run.manifest.total_duration_seconds.toFixed(2)} 秒 · {run.manifest.composer_version}</p></details>}
    </section>
  );
}
