"use client";

import { useCallback, useEffect, useState } from "react";

import type {
  ArtifactDescriptor,
  Audience,
  CodeGenerationCategory,
  CodeVersion,
  ContentPlanDraft,
  ContentPlanScene,
  ContentPlanVersion,
  DerivationStyle,
  FormulaStep,
  Project,
  PromptVersion,
  RenderJob,
} from "@manim-workbench/contracts";

import { ApiClientError, workbenchApi } from "../../lib/api/client";

import { useRenderMonitor } from "./use-render-monitor";

export type EditableScene = Omit<ContentPlanScene, "formula_steps"> & {
  formula_steps: FormulaStep[];
};

export type PlanEditor = {
  title: string;
  audience: Audience;
  target_duration_seconds: number;
  derivation_style: DerivationStyle;
  explicit_assumptions: string[];
  ambiguities: string[];
  scenes: EditableScene[];
};

const blankScene = (scene_number: number): EditableScene => ({
  scene_number,
  teaching_goal: "说明这个步骤的教学目标",
  formula_steps: [{ expression: "", explanation: "" }],
  visual_intent: "使用清晰的动态标注强调关键关系。",
  narration_placeholder: "解释这一画面的重点。",
});

const asEditor = (plan: ContentPlanVersion): PlanEditor => ({
  title: plan.title,
  audience: plan.audience,
  target_duration_seconds: plan.target_duration_seconds,
  derivation_style: plan.derivation_style ?? "step_by_step",
  explicit_assumptions: [...plan.explicit_assumptions],
  ambiguities: [...(plan.ambiguities ?? [])],
  scenes: plan.scenes.map((scene) => ({ ...scene, formula_steps: [...scene.formula_steps] })),
});

const asDraft = (editor: PlanEditor): ContentPlanDraft => ({
  schema_version: "1.1",
  title: editor.title.trim(),
  audience: editor.audience,
  language: "zh-CN",
  target_duration_seconds: editor.target_duration_seconds,
  derivation_style: editor.derivation_style,
  explicit_assumptions: editor.explicit_assumptions.filter(Boolean),
  ambiguities: editor.ambiguities.filter(Boolean),
  scenes: editor.scenes.map((scene, index) => ({
    ...scene,
    scene_number: index + 1,
    formula_steps: scene.formula_steps.filter((step) => step.expression || step.explanation),
  })),
});

const messageFor = (cause: unknown) => {
  if (cause instanceof ApiClientError) {
    return cause.stage ? `${cause.stage}：${cause.message}` : cause.message;
  }
  return "操作未完成，请稍后重试。";
};

const mergeVersions = <T extends { id: string }>(
  current: ReadonlyArray<T>,
  incoming: ReadonlyArray<T>,
) => [...current, ...incoming.filter((item) => !current.some((existing) => existing.id === item.id))];

export function useWorkbench() {
  const [projects, setProjects] = useState<ReadonlyArray<Project>>([]);
  const [activeProject, setActiveProject] = useState<Project | null>(null);
  const [prompts, setPrompts] = useState<ReadonlyArray<PromptVersion>>([]);
  const [plans, setPlans] = useState<ReadonlyArray<ContentPlanVersion>>([]);
  const [promptCursor, setPromptCursor] = useState<number | null>(null);
  const [planCursor, setPlanCursor] = useState<number | null>(null);
  const [activePrompt, setActivePrompt] = useState<PromptVersion | null>(null);
  const [activePlan, setActivePlan] = useState<ContentPlanVersion | null>(null);
  const [planEditor, setPlanEditor] = useState<PlanEditor | null>(null);
  const [codeVersion, setCodeVersion] = useState<CodeVersion | null>(null);
  const [category, setCategory] = useState<CodeGenerationCategory>("formula_derivation");
  const [job, setJob] = useState<RenderJob | null>(null);
  const [artifacts, setArtifacts] = useState<ReadonlyArray<ArtifactDescriptor>>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadProject = useCallback(async (project: Project) => {
    setBusy(true);
    setMessage(null);
    try {
      const [promptPage, planPage] = await Promise.all([
        workbenchApi.listPromptVersions(project.id),
        workbenchApi.listContentPlanVersions(project.id),
      ]);
      setActiveProject(project);
      setPrompts(promptPage.items);
      setPlans(planPage.items);
      setPromptCursor(promptPage.next_cursor ?? null);
      setPlanCursor(planPage.next_cursor ?? null);
      setActivePrompt(promptPage.items[0] ?? null);
      const latestPlan = planPage.items[0] ?? null;
      setActivePlan(latestPlan);
      setPlanEditor(latestPlan ? asEditor(latestPlan) : null);
      const query = new URLSearchParams(window.location.search);
      query.set("project", project.id);
      window.history.replaceState(null, "", `/workbench?${query.toString()}`);
    } catch (cause) {
      setMessage(messageFor(cause));
    } finally {
      setBusy(false);
    }
  }, []);

  const loadMorePrompts = useCallback(async () => {
    if (!activeProject || promptCursor === null) return;
    try {
      const page = await workbenchApi.listPromptVersions(activeProject.id, promptCursor);
      setPrompts((current) => mergeVersions(current, page.items));
      setPromptCursor(page.next_cursor ?? null);
    } catch (cause) {
      setMessage(messageFor(cause));
    }
  }, [activeProject, promptCursor]);

  const loadMorePlans = useCallback(async () => {
    if (!activeProject || planCursor === null) return;
    try {
      const page = await workbenchApi.listContentPlanVersions(activeProject.id, planCursor);
      setPlans((current) => mergeVersions(current, page.items));
      setPlanCursor(page.next_cursor ?? null);
    } catch (cause) {
      setMessage(messageFor(cause));
    }
  }, [activeProject, planCursor]);

  const loadProjects = useCallback(async () => {
    setBusy(true);
    try {
      const page = await workbenchApi.listProjects();
      setProjects(page.items);
      const selectedId = new URLSearchParams(window.location.search).get("project");
      const selected = page.items.find((project) => project.id === selectedId) ?? page.items[0];
      if (selected) await loadProject(selected);
    } catch (cause) {
      setMessage(messageFor(cause));
    } finally {
      setBusy(false);
    }
  }, [loadProject]);

  const loadArtifacts = useCallback(async (jobId: string) => {
    setArtifacts(await workbenchApi.listArtifacts(jobId));
  }, []);

  useRenderMonitor(job?.id ?? null, setJob, setMessage);

  useEffect(() => {
    if (job?.status !== "succeeded") return;
    const timer = window.setTimeout(() => {
      void loadArtifacts(job.id).catch(() => setMessage("产物正在发布，请稍后刷新。"));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [job, loadArtifacts]);

  const recoverRenderJob = useCallback(async () => {
    const jobId = new URLSearchParams(window.location.search).get("job");
    if (!jobId) return;
    try {
      setJob(await workbenchApi.getRenderJob(jobId));
    } catch {
      setMessage("无法恢复之前的渲染任务。");
    }
  }, []);

  const createProject = useCallback(async (title: string) => {
    if (!title.trim()) return setMessage("请先填写项目名称。");
    setBusy(true);
    try {
      const project = await workbenchApi.createProject({ title: title.trim() });
      setProjects((current) => [...current, project]);
      await loadProject(project);
    } catch (cause) {
      setMessage(messageFor(cause));
    } finally {
      setBusy(false);
    }
  }, [loadProject]);

  const generatePlan = useCallback(async (input: {
    prompt: string; audience: Audience; duration: number; style: DerivationStyle; assumptions: string[];
  }) => {
    if (!activeProject || !input.prompt.trim()) return setMessage("选择项目并填写 Prompt 后才能生成。 ");
    setBusy(true);
    setMessage(null);
    try {
      const prompt = await workbenchApi.createPromptVersion(activeProject.id, { prompt: input.prompt.trim() });
      const result = await workbenchApi.generateContentPlan(activeProject.id, {
        prompt_version_id: prompt.id,
        audience: input.audience,
        language: "zh-CN",
        target_duration_seconds: input.duration,
        derivation_style: input.style,
        explicit_assumptions: input.assumptions.filter(Boolean),
      });
      setPrompts((current) => [prompt, ...current]);
      setActivePrompt(prompt);
      if (!result.content_plan_version) {
        setMessage("生成需要补充信息，请调整左侧输入后重试。");
        return;
      }
      setPlans((current) => [result.content_plan_version!, ...current]);
      setActivePlan(result.content_plan_version);
      setPlanEditor(asEditor(result.content_plan_version));
      setMessage("ContentPlan 已生成，可在中栏确认后保存新版本。");
    } catch (cause) {
      setMessage(messageFor(cause));
    } finally {
      setBusy(false);
    }
  }, [activeProject]);

  const savePlan = useCallback(async () => {
    if (!activeProject || !activePlan || !planEditor) return;
    setBusy(true);
    try {
      const saved = await workbenchApi.saveContentPlanVersion(activeProject.id, {
        parent_version_id: activePlan.id,
        content_plan: asDraft(planEditor),
      });
      setPlans((current) => [saved, ...current]);
      setActivePlan(saved);
      setPlanEditor(asEditor(saved));
      setMessage(`已保存 ContentPlan v${saved.version}。`);
    } catch (cause) {
      setMessage(messageFor(cause));
    } finally {
      setBusy(false);
    }
  }, [activePlan, activeProject, planEditor]);

  const selectPlan = useCallback((plan: ContentPlanVersion) => {
    setActivePlan(plan);
    setPlanEditor(asEditor(plan));
  }, []);

  const generateCode = useCallback(async (category: CodeGenerationCategory) => {
    if (!activeProject || !activePrompt || !activePlan) return setMessage("请先确认 Prompt 和 ContentPlan。 ");
    setBusy(true);
    try {
      const result = await workbenchApi.generateCode(activeProject.id, {
        prompt_version_id: activePrompt.id,
        content_plan_version_id: activePlan.id,
        category,
      });
      if (!result.code_version) return setMessage("代码生成未完成，请查看阶段错误后重试。");
      setCodeVersion(result.code_version);
      setMessage(`已生成 CodeVersion v${result.code_version.version}。`);
    } catch (cause) {
      setMessage(messageFor(cause));
    } finally {
      setBusy(false);
    }
  }, [activePlan, activeProject, activePrompt]);

  const submitRender = useCallback(async (profile: "preview" | "final") => {
    if (!activeProject || !codeVersion) return setMessage("请先生成可渲染的 CodeVersion。 ");
    setBusy(true);
    try {
      const nextJob = await workbenchApi.submitRenderJob(activeProject.id, {
        code_version_id: codeVersion.id,
        profile,
        idempotency_key: crypto.randomUUID(),
      });
      setArtifacts([]);
      setJob(nextJob);
      window.history.replaceState(null, "", `/workbench?project=${activeProject.id}&job=${nextJob.id}`);
    } catch (cause) {
      setMessage(messageFor(cause));
    } finally {
      setBusy(false);
    }
  }, [activeProject, codeVersion]);

  const cancelRender = useCallback(async () => {
    if (!job) return;
    try {
      setJob(await workbenchApi.cancelRenderJob(job.id));
    } catch (cause) {
      setMessage(messageFor(cause));
    }
  }, [job]);

  return {
    projects, activeProject, prompts, plans, promptCursor, planCursor, activePrompt, activePlan, planEditor, codeVersion, category,
    job, artifacts, message, busy, setMessage, setPlanEditor, setActivePlan, setActivePrompt, setCategory,
    loadProjects, loadProject, loadMorePrompts, loadMorePlans, recoverRenderJob, createProject, generatePlan, savePlan, selectPlan,
    generateCode, submitRender, cancelRender, blankScene,
  };
}
