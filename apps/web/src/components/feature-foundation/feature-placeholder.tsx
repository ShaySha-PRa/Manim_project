"use client";

import { Button } from "../ui/button";
import { Panel } from "../ui/panel";
import { StatusMessage } from "../ui/status-message";
import { useWorkbenchSession } from "../../hooks/workbench/use-workbench-session";

type FeatureKind = "lab" | "studio";

type FeatureCopy = {
  readonly eyebrow: string;
  readonly title: string;
  readonly introduction: string;
  readonly status: string;
  readonly nextStep: string;
};

const FEATURE_COPY: Record<FeatureKind, FeatureCopy> = {
  lab: {
    eyebrow: "实验室基础入口",
    title: "科学实验室",
    introduction: "这里将承载可观察、可复现的数学模型实验。当前先冻结入口和实验契约。",
    status: "科学运行时、求解器、实时交互或实时渲染未启用。",
    nextStep: "后续里程碑将逐步接入模型运行与浏览器交互。",
  },
  studio: {
    eyebrow: "讲解工作流基础入口",
    title: "Studio",
    introduction: "这里将承载从实验构思到教学讲解的整理工作。当前先保留受保护入口。",
    status: "实验到讲解叙事的工作流或 Manim 视频生成未启用。",
    nextStep: "现有 Workbench 的 Prompt、ContentPlan、CodeVersion 和视频流程保持不变。",
  },
};

function FeaturePlaceholder({ feature }: Readonly<{ feature: FeatureKind }>) {
  const session = useWorkbenchSession();
  const copy = FEATURE_COPY[feature];

  return (
    <main
      aria-busy={session.state === "loading"}
      className="feature-page"
      id="main-content"
    >
      <div className="feature-page__shell">
        {session.state === "loading" ? (
          <section aria-label="会话状态" className="feature-page__state">
            <StatusMessage>正在恢复安全会话…</StatusMessage>
          </section>
        ) : null}

        {session.state === "error" ? (
          <section aria-label="会话错误" className="feature-page__state">
            <StatusMessage tone="error">{session.error ?? "无法恢复会话。"}</StatusMessage>
            <Button onClick={() => void session.recover()} variant="secondary">
              重试
            </Button>
          </section>
        ) : null}

        {session.state === "ready" ? (
          <Panel aria-labelledby="feature-title" className="feature-page__panel">
            <p className="eyebrow">{copy.eyebrow}</p>
            <h1 id="feature-title">{copy.title}</h1>
            <p className="feature-page__introduction">{copy.introduction}</p>
            <div className="feature-page__details">
              <section aria-labelledby="feature-status-title" className="feature-page__detail">
                <p className="feature-page__label" id="feature-status-title">
                  当前状态
                </p>
                <p>{copy.status}</p>
              </section>
              <section aria-labelledby="feature-next-step-title" className="feature-page__detail">
                <p className="feature-page__label" id="feature-next-step-title">
                  后续范围
                </p>
                <p>{copy.nextStep}</p>
              </section>
            </div>
          </Panel>
        ) : null}
      </div>
    </main>
  );
}

export function LabPlaceholder() {
  return <FeaturePlaceholder feature="lab" />;
}

export function StudioPlaceholder() {
  return <FeaturePlaceholder feature="studio" />;
}
