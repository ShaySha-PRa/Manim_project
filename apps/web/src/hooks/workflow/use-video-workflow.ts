"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { DirectorPlan, Project, SceneRunProvenance } from "@manim-workbench/contracts";

import type {
  CompositionRun,
  GlobalBrief,
  RenderProfile,
  SceneBlockRun,
  SceneDraft,
  VideoWorkflow,
  VideoWorkflowVersion,
  WorkflowEdge,
  WorkflowNode,
} from "../../components/workflow/types";
import {
  ApiClientError,
  createIdempotencyKey,
  workbenchApi,
} from "../../lib/api/client";

const newLocalId = () => globalThis.crypto.randomUUID();

const blankScene = (index: number): SceneDraft => ({
  localId: newLocalId(),
  blockId: null,
  version: null,
  title: `场景 ${index}`,
  prompt: "",
  pipelineMode: "auto",
  targetDurationSeconds: 30,
  assetVersionIds: [],
  dirty: true,
});

const defaultBrief: GlobalBrief = {
  title: "新的科学动画",
  language: "zh-CN",
  target_duration_seconds: 90,
  aspect_ratio: "16:9",
  style_preset: "dark_scientific",
  background: "#101018",
  palette: ["#4488ff", "#ffcc22", "#ff4444"],
  notation: {},
  scientific_parameters: {},
};

const terminalScene = new Set(["succeeded", "failed", "asset_required", "needs_confirmation"]);
const terminalComposition = new Set(["succeeded", "failed", "not_ready_to_compose"]);

export const sceneRunKey = (versionId: string, profile: RenderProfile) =>
  `${versionId}:${profile}`;

export function retainRunsForCurrentScenes(
  currentRuns: Readonly<Record<string, SceneBlockRun>>,
  currentScenes: ReadonlyArray<SceneDraft>,
): Readonly<Record<string, SceneBlockRun>> {
  const versionIds = new Set(
    currentScenes.flatMap((scene) => scene.version ? [scene.version.id] : []),
  );
  return Object.fromEntries(
    Object.entries(currentRuns).filter(([, run]) => versionIds.has(run.scene_block_version_id)),
  );
}

const messageFor = (cause: unknown) =>
  cause instanceof ApiClientError ? cause.message : "操作未完成，请稍后重试。";

export function useVideoWorkflow(enabled: boolean) {
  const [projects, setProjects] = useState<ReadonlyArray<Project>>([]);
  const [projectId, setProjectId] = useState("");
  const [workflow, setWorkflow] = useState<VideoWorkflow | null>(null);
  const [version, setVersion] = useState<VideoWorkflowVersion | null>(null);
  const [brief, setBrief] = useState<GlobalBrief>(defaultBrief);
  const [scenes, setScenes] = useState<ReadonlyArray<SceneDraft>>([
    blankScene(1),
    blankScene(2),
  ]);
  const [runs, setRuns] = useState<Readonly<Record<string, SceneBlockRun>>>({});
  const [provenance, setProvenance] = useState<Readonly<Record<string, SceneRunProvenance>>>({});
  const [composition, setComposition] = useState<CompositionRun | null>(null);
  const [directorObjective, setDirectorObjective] = useState("");
  const [directorPlan, setDirectorPlan] = useState<DirectorPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const submissions = useRef(new Set<string>());

  const recover = useCallback(async () => {
    const page = await workbenchApi.listProjects();
    setProjects(page.items);
    const query = new URLSearchParams(window.location.search);
    const selectedProject = query.get("project") ?? page.items[0]?.id ?? "";
    setProjectId(selectedProject);
    const directorId = query.get("director");
    if (directorId && selectedProject) {
      setDirectorPlan(await workbenchApi.getDirectorPlan(selectedProject, directorId));
    }
    const versionId = query.get("version");
    if (!versionId) return;
    const recoveredVersion = await workbenchApi.getVideoWorkflowVersion(versionId);
    const recoveredWorkflow = await workbenchApi.getVideoWorkflow(recoveredVersion.workflow_id);
    const sceneNodes = recoveredVersion.nodes.filter((node) => node.kind === "scene");
    const details = await Promise.all(
      sceneNodes.map((node) => workbenchApi.getSceneBlockVersion(node.scene_block_version_id!)),
    );
    setWorkflow(recoveredWorkflow);
    setVersion(recoveredVersion);
    setBrief(recoveredVersion.global_brief);
    setScenes(details.map(({ block_id, version: sceneVersion }) => ({
      localId: newLocalId(),
      blockId: block_id,
      version: sceneVersion,
      title: sceneVersion.title,
      prompt: sceneVersion.prompt,
      pipelineMode: sceneVersion.pipeline_mode,
      targetDurationSeconds: sceneVersion.target_duration_seconds,
      assetVersionIds: sceneVersion.asset_version_ids,
      dirty: false,
    })));
    const runIds = (query.get("runs") ?? "").split(",").filter(Boolean);
    const recoveredRuns = await Promise.all(runIds.map((id) => workbenchApi.getSceneBlockRun(id)));
    setRuns(Object.fromEntries(recoveredRuns.map((run) => [
      sceneRunKey(run.scene_block_version_id, run.profile), run,
    ])));
    const compositionId = query.get("composition");
    if (compositionId) setComposition(await workbenchApi.getCompositionRun(compositionId));
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const timer = window.setTimeout(() => {
      void recover().catch((cause) => setMessage(messageFor(cause)));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [enabled, recover]);

  useEffect(() => {
    if (!directorPlan || !["queued", "planning"].includes(directorPlan.status)) return;
    const timer = window.setInterval(() => {
      void workbenchApi.getDirectorPlan(directorPlan.project_id, directorPlan.id)
        .then(setDirectorPlan)
        .catch(() => setMessage("Director 状态暂时无法刷新，正在保留计划身份。"));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [directorPlan]);

  useEffect(() => {
    const activeRuns = Object.values(runs).filter((run) => !terminalScene.has(run.status));
    const activeComposition = composition && !terminalComposition.has(composition.status)
      ? composition
      : null;
    if (!activeRuns.length && !activeComposition) return;
    const timer = window.setInterval(() => {
      void Promise.all(activeRuns.map((run) => workbenchApi.getSceneBlockRun(run.id)))
        .then((updated) => setRuns((current) => ({
          ...current,
          ...Object.fromEntries(updated.map((run) => [
            sceneRunKey(run.scene_block_version_id, run.profile), run,
          ])),
        })))
        .catch(() => setMessage("场景状态暂时无法刷新，正在保留当前任务身份。"));
      if (activeComposition) {
        void workbenchApi.getCompositionRun(activeComposition.id)
          .then(setComposition)
          .catch(() => setMessage("整片状态暂时无法刷新，稍后将继续恢复。"));
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [composition, runs]);

  const updateUrl = useCallback((nextVersion: VideoWorkflowVersion, nextRuns = runs, nextComposition = composition) => {
    const query = new URLSearchParams();
    query.set("project", nextVersion.project_id);
    query.set("workflow", nextVersion.workflow_id);
    query.set("version", nextVersion.id);
    const runIds = Object.values(nextRuns).map((run) => run.id);
    if (runIds.length) query.set("runs", runIds.join(","));
    if (nextComposition) query.set("composition", nextComposition.id);
    window.history.replaceState(null, "", `/workflows?${query.toString()}`);
  }, [composition, runs]);

  const updateScene = useCallback((localId: string, patch: Partial<SceneDraft>) => {
    setScenes((current) => current.map((scene) => (
      scene.localId === localId ? { ...scene, ...patch, dirty: true } : scene
    )));
  }, []);

  const planWithDirector = useCallback(async () => {
    if (!projectId) return setMessage("请先选择项目。");
    if (!directorObjective.trim()) return setMessage("请描述完整视频要解释和展示什么。");
    setBusy(true);
    setMessage(null);
    try {
      const plan = await workbenchApi.createDirectorPlan(projectId, {
        objective: directorObjective.trim(),
        title: brief.title || null,
        language: brief.language,
        target_duration_seconds: brief.target_duration_seconds,
        style_preset: brief.style_preset,
        asset_version_ids: [],
        idempotency_key: createIdempotencyKey(),
      });
      setDirectorPlan(plan);
      const query = new URLSearchParams(window.location.search);
      query.set("project", projectId);
      query.set("director", plan.id);
      window.history.replaceState(null, "", `/workflows?${query.toString()}`);
      setMessage("Director 已开始拆分整片结构。完成后可应用为场景草稿。");
    } catch (cause) {
      setMessage(messageFor(cause));
    } finally {
      setBusy(false);
    }
  }, [brief, directorObjective, projectId]);

  const persist = useCallback(async () => {
    if (!projectId) return setMessage("请先选择项目。");
    if (scenes.length < 2 || scenes.length > 8) return setMessage("工作流需要 2–8 个场景。");
    if (scenes.some((scene) => !scene.title.trim() || !scene.prompt.trim())) {
      return setMessage("每个场景都需要标题和自然语言描述。");
    }
    if (scenes.reduce((total, scene) => total + scene.targetDurationSeconds, 0) > 600) {
      return setMessage("所有场景目标时长合计不能超过 600 秒。");
    }
    setBusy(true);
    setMessage(null);
    try {
      const activeWorkflow = workflow ?? await workbenchApi.createVideoWorkflow(projectId);
      const persisted = [] as SceneDraft[];
      for (const scene of scenes) {
        if (!scene.version || !scene.blockId) {
          const created = await workbenchApi.createSceneBlock(activeWorkflow.id, {
            title: scene.title.trim(),
            prompt: scene.prompt.trim(),
            pipeline_mode: scene.pipelineMode,
            target_duration_seconds: scene.targetDurationSeconds,
            asset_version_ids: scene.assetVersionIds,
          });
          persisted.push({ ...scene, blockId: created.block.id, version: created.version, dirty: false });
        } else if (scene.dirty) {
          const next = await workbenchApi.createSceneBlockVersion(scene.blockId, {
            parent_version_id: scene.version.id,
            title: scene.title.trim(),
            prompt: scene.prompt.trim(),
            pipeline_mode: scene.pipelineMode,
            target_duration_seconds: scene.targetDurationSeconds,
            asset_version_ids: scene.assetVersionIds,
          });
          persisted.push({ ...scene, version: next, dirty: false });
        } else {
          persisted.push(scene);
        }
      }
      const nodeIds = Array.from({ length: persisted.length + 2 }, newLocalId);
      const nodes: WorkflowNode[] = persisted.map((scene, index) => ({
        id: nodeIds[index],
        kind: "scene",
        scene_block_version_id: scene.version!.id,
      }));
      nodes.push({ id: nodeIds.at(-2)!, kind: "compose" });
      nodes.push({ id: nodeIds.at(-1)!, kind: "export" });
      const edges: WorkflowEdge[] = nodeIds.slice(0, -1).map((id, index) => ({
        source_node_id: id,
        target_node_id: nodeIds[index + 1],
      }));
      const nextVersion = await workbenchApi.createVideoWorkflowVersion(activeWorkflow.id, {
        parent_version_id: version?.id ?? null,
        global_brief: brief,
        nodes,
        edges,
      });
      setWorkflow(activeWorkflow);
      setVersion(nextVersion);
      setScenes(persisted);
      const retainedRuns = retainRunsForCurrentScenes(runs, persisted);
      setRuns(retainedRuns);
      setComposition(null);
      updateUrl(nextVersion, retainedRuns, null);
      setMessage(`已保存 Workflow v${nextVersion.version}。`);
    } catch (cause) {
      setMessage(messageFor(cause));
    } finally {
      setBusy(false);
    }
  }, [brief, projectId, runs, scenes, updateUrl, version, workflow]);

  const submitScene = useCallback(async (scene: SceneDraft, profile: RenderProfile) => {
    if (!version || !scene.version) return setMessage("请先保存工作流版本。");
    const submissionKey = `${scene.version.id}:${profile}`;
    if (submissions.current.has(submissionKey)) return;
    submissions.current.add(submissionKey);
    try {
      return await workbenchApi.submitSceneBlockRun(scene.version.id, {
        workflow_version_id: version.id,
        profile,
        idempotency_key: createIdempotencyKey(),
      });
    } catch (cause) {
      setMessage(messageFor(cause));
    } finally {
      submissions.current.delete(submissionKey);
    }
  }, [version]);

  const applyDirectorPlan = useCallback(async () => {
    if (!directorPlan?.draft || directorPlan.status !== "ready") {
      return setMessage("Director 草稿尚未 ready；请先处理确认或资产需求。");
    }
    setBusy(true);
    try {
      const nextVersion = await workbenchApi.applyDirectorPlan(
        directorPlan.project_id,
        directorPlan.id,
        {
          draft: directorPlan.draft,
          scene_asset_version_ids: directorPlan.draft.scenes.map(() => []),
          idempotency_key: createIdempotencyKey(),
        },
      );
      const nextWorkflow = await workbenchApi.getVideoWorkflow(nextVersion.workflow_id);
      const details = await Promise.all(
        nextVersion.nodes.filter((node) => node.kind === "scene")
          .map((node) => workbenchApi.getSceneBlockVersion(node.scene_block_version_id!)),
      );
      const nextScenes = details.map(({ block_id, version: sceneVersion }) => ({
        localId: newLocalId(),
        blockId: block_id,
        version: sceneVersion,
        title: sceneVersion.title,
        prompt: sceneVersion.prompt,
        pipelineMode: sceneVersion.pipeline_mode,
        targetDurationSeconds: sceneVersion.target_duration_seconds,
        assetVersionIds: sceneVersion.asset_version_ids,
        dirty: false,
      }));
      setWorkflow(nextWorkflow);
      setVersion(nextVersion);
      setBrief(nextVersion.global_brief);
      setScenes(nextScenes);
      setRuns({});
      setComposition(null);
      updateUrl(nextVersion, {}, null);
      setMessage("Director 草稿已应用。你可以修改场景，然后生成全部 Preview。");
    } catch (cause) {
      setMessage(messageFor(cause));
    } finally {
      setBusy(false);
    }
  }, [directorPlan, updateUrl]);

  const uploadCsv = useCallback(async (scene: SceneDraft, csvText: string) => {
    if (!projectId) return setMessage("请先选择项目。");
    try {
      const asset = await workbenchApi.createScientificCsvAsset(projectId, csvText);
      updateScene(scene.localId, {
        assetVersionIds: [...scene.assetVersionIds, asset.id],
      });
      setMessage("CSV 已保存为不可变 AssetVersion；请保存工作流新版本后生成。");
    } catch (cause) {
      setMessage(messageFor(cause));
    }
  }, [projectId, updateScene]);

  const loadProvenance = useCallback(async (run: SceneBlockRun) => {
    try {
      const detail = await workbenchApi.getSceneRunProvenance(run.id);
      setProvenance((current) => ({ ...current, [run.id]: detail }));
    } catch (cause) {
      setMessage(messageFor(cause));
    }
  }, []);

  const generateScene = useCallback(async (scene: SceneDraft, profile: RenderProfile) => {
    const run = await submitScene(scene, profile);
    if (!run || !version) return;
    const nextRuns = {
      ...runs,
      [sceneRunKey(run.scene_block_version_id, run.profile)]: run,
    };
    setRuns(nextRuns);
    updateUrl(version, nextRuns, composition);
  }, [composition, runs, submitScene, updateUrl, version]);

  const generateIncomplete = useCallback(async (profile: RenderProfile) => {
    const incomplete = scenes.filter((scene) => (
      scene.version && runs[sceneRunKey(scene.version.id, profile)]?.status !== "succeeded"
    ));
    const submitted = [] as SceneBlockRun[];
    for (const scene of incomplete) {
      const run = await submitScene(scene, profile);
      if (run) submitted.push(run);
    }
    if (!submitted.length || !version) return;
    const nextRuns = {
      ...runs,
      ...Object.fromEntries(submitted.map((run) => [
        sceneRunKey(run.scene_block_version_id, run.profile), run,
      ])),
    };
    setRuns(nextRuns);
    updateUrl(version, nextRuns, composition);
  }, [composition, runs, scenes, submitScene, updateUrl, version]);

  const compose = useCallback(async (profile: RenderProfile) => {
    if (!version) return setMessage("请先保存工作流版本。");
    const submissionKey = `${version.id}:compose:${profile}`;
    if (submissions.current.has(submissionKey)) return;
    submissions.current.add(submissionKey);
    try {
      const run = await workbenchApi.submitCompositionRun(version.id, {
        profile,
        idempotency_key: createIdempotencyKey(),
      });
      setComposition(run);
      updateUrl(version, runs, run);
    } catch (cause) {
      setMessage(messageFor(cause));
    } finally {
      submissions.current.delete(submissionKey);
    }
  }, [runs, updateUrl, version]);

  const moveScene = useCallback((index: number, delta: -1 | 1) => {
    setScenes((current) => {
      const target = index + delta;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }, []);

  const reorderScene = useCallback((from: number, to: number) => {
    setScenes((current) => {
      if (from === to || from < 0 || to < 0 || from >= current.length || to >= current.length) {
        return current;
      }
      const next = [...current];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });
  }, []);

  const allSucceeded = useCallback((profile: RenderProfile) => scenes.every((scene) => (
    scene.version && runs[sceneRunKey(scene.version.id, profile)]?.status === "succeeded"
  )), [runs, scenes]);

  const runFor = useCallback((scene: SceneDraft, profile: RenderProfile) => (
    scene.version ? runs[sceneRunKey(scene.version.id, profile)] : undefined
  ), [runs]);

  return {
    projects, projectId, setProjectId, workflow, version, brief, setBrief, scenes, setScenes,
    runs, provenance, composition, busy, message, setMessage, persist, updateScene, generateScene,
    generateIncomplete, compose, moveScene, reorderScene, allSucceeded, runFor, uploadCsv,
    loadProvenance, directorObjective, setDirectorObjective, directorPlan, planWithDirector,
    applyDirectorPlan,
    addScene: () => setScenes((current) => current.length < 8
      ? [...current, blankScene(current.length + 1)] : current),
    copyScene: (scene: SceneDraft) => setScenes((current) => current.length < 8
      ? [...current, { ...scene, localId: newLocalId(), blockId: null, version: null, dirty: true }]
      : current),
    removeDraft: (localId: string) => setScenes((current) => current.length > 2
      ? current.filter((scene) => scene.localId !== localId || scene.blockId !== null)
      : current),
  };
}
