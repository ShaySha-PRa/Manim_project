import { workbenchApi } from "../../lib/api/client";
import type { SceneBlockRun } from "./types";

import styles from "../../app/workflows/workflows.module.css";

export function ScenePreview({ run }: { run: SceneBlockRun | undefined }) {
  if (!run) return <p className={styles.empty}>保存并生成后可预览。</p>;
  const artifactId = run.final_artifact_id ?? run.preview_artifact_id;
  if (run.status !== "succeeded" || !artifactId) {
    return <p className={styles.empty}>{run.status === "asset_required" ? "需要绑定资产，不会生成占位视频。" : run.status === "needs_confirmation" ? "需要确认场景类型或资料，不会猜测内容。" : `状态：${run.status}`}</p>;
  }
  return <video className={styles.video} controls preload="metadata" src={workbenchApi.artifactUrl(artifactId)} />;
}
