"use client";

import type { ArtifactDescriptor } from "@manim-workbench/contracts";
import Image from "next/image";

import { workbenchApi } from "../../lib/api/client";
import { QualityPanel } from "../quality/quality-panel";
import type { WorkbenchModel } from "./types";
import { PythonReadOnly } from "./python-read-only";
import styles from "../../app/workbench/workbench.module.css";

const terminal = new Set(["succeeded", "failed", "cancelled"]);

function absoluteUrl(relative: string) {
  return new URL(relative, workbenchApi.baseUrl).toString();
}

function Artifacts({ artifacts }: { artifacts: ReadonlyArray<ArtifactDescriptor> }) {
  const video = artifacts.find((artifact) => artifact.kind === "video");
  const thumbnail = artifacts.find((artifact) => artifact.kind === "thumbnail");
  if (!artifacts.length) return <p className={styles.muted}>渲染完成后将在这里提供预览与下载。</p>;
  return (
    <div className={styles.artifacts}>
      {video && <video controls preload="metadata" src={absoluteUrl(video.preview_url)}>当前浏览器无法播放预览视频。</video>}
      {thumbnail && <Image unoptimized width={1600} height={900} src={absoluteUrl(thumbnail.preview_url)} alt="渲染视频缩略图" />}
      <div className={styles.downloads}>
        {artifacts.filter((artifact) => artifact.kind !== "metadata").map((artifact) => (
          <a href={absoluteUrl(artifact.download_url)} key={artifact.id}>下载{artifact.kind === "video" ? "视频" : artifact.kind === "thumbnail" ? "缩略图" : "渲染日志"}</a>
        ))}
      </div>
    </div>
  );
}

export function RenderPanel({ model }: { model: WorkbenchModel }) {
  const job = model.job;
  return (
    <section className={styles.column} aria-labelledby="render-heading">
      <div className={styles.sectionHeading}><p>03 · 生成与交付</p><h2 id="render-heading">CodeVersion 与渲染</h2></div>
      <p className={styles.muted}>确认 ContentPlan 后生成受控 Manim 代码，再选择预览或终渲。</p>
      <button className={styles.primaryButton} type="button" disabled={model.busy || !model.activePlan || !model.activePrompt} onClick={() => void model.generateCode(model.category)}>生成 CodeVersion</button>
      <div className={styles.actionRow}>
        <button type="button" disabled={model.busy || !model.codeVersion} onClick={() => void model.submitRender("preview")}>提交预览</button>
        <button type="button" disabled={model.busy || !model.codeVersion} onClick={() => void model.submitRender("final")}>提交终渲</button>
      </div>
      <section className={styles.jobCard} aria-live="polite" aria-atomic="true">
        <h3>任务状态</h3>
        {!job && <p className={styles.empty}>尚未提交渲染任务。</p>}
        {job && <>
          <p><strong>{job.profile === "preview" ? "预览" : "终渲"}</strong> · {job.status}</p>
          <p className={styles.muted}>尝试次数：{job.attempt_count ?? 0} · 状态版本：{job.state_version ?? 0}</p>
          {job.failure_code && <p className={styles.error}>渲染阶段错误：{job.failure_code}</p>}
          {!terminal.has(job.status) && <button type="button" className={styles.dangerButton} onClick={() => void model.cancelRender()}>取消任务</button>}
        </>}
      </section>
      <QualityPanel jobId={job?.id} refreshKey={job?.state_version} />
      <section aria-labelledby="artifact-heading"><h3 id="artifact-heading">视频与产物</h3><Artifacts artifacts={model.artifacts} /></section>
      <PythonReadOnly codeVersion={model.codeVersion} />
    </section>
  );
}
