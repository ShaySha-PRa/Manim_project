export type WorkflowStyle =
  | "dark_scientific"
  | "light_academic"
  | "minimal_math"
  | "presentation";

export type ScenePipelineMode = "auto" | "teaching" | "scientific";
export type RenderProfile = "preview" | "final";

export type GlobalBrief = {
  title: string;
  language: "zh-CN" | "en-US";
  target_duration_seconds: number;
  aspect_ratio: "16:9";
  style_preset: WorkflowStyle;
  background: string;
  palette: ReadonlyArray<string>;
  notation: Readonly<Record<string, string>>;
  scientific_parameters: Readonly<Record<string, number>>;
};

export type SceneBlockVersion = {
  id: string;
  project_id: string;
  workflow_id: string;
  owner_id: string;
  version: number;
  parent_version_id: string | null;
  title: string;
  prompt: string;
  pipeline_mode: ScenePipelineMode;
  target_duration_seconds: number;
  asset_version_ids: ReadonlyArray<string>;
  created_at: string;
};

export type SceneDraft = {
  localId: string;
  blockId: string | null;
  version: SceneBlockVersion | null;
  title: string;
  prompt: string;
  pipelineMode: ScenePipelineMode;
  targetDurationSeconds: number;
  assetVersionIds: ReadonlyArray<string>;
  dirty: boolean;
};

export type WorkflowNode = {
  id: string;
  kind: "scene" | "compose" | "export";
  scene_block_version_id?: string | null;
};

export type WorkflowEdge = { source_node_id: string; target_node_id: string };

export type VideoWorkflow = {
  id: string;
  project_id: string;
  owner_id: string;
  created_at: string;
};

export type VideoWorkflowVersion = {
  id: string;
  workflow_id: string;
  project_id: string;
  owner_id: string;
  version: number;
  parent_version_id: string | null;
  global_brief: GlobalBrief;
  nodes: ReadonlyArray<WorkflowNode>;
  edges: ReadonlyArray<WorkflowEdge>;
  created_at: string;
};

export type SceneBlockRun = {
  id: string;
  project_id: string;
  owner_id: string;
  scene_block_version_id: string;
  profile: RenderProfile;
  status: "queued" | "planning" | "needs_confirmation" | "asset_required" | "compiling" | "rendering" | "succeeded" | "failed";
  pipeline_used: "teaching" | "scientific" | null;
  intent_ref: string | null;
  animation_ir_ref: string | null;
  compiled_program_ref: string | null;
  preview_artifact_id: string | null;
  final_artifact_id: string | null;
  cache_key: string;
  error_code: string | null;
  state_version: number;
  created_at: string;
};

export type CompositionRun = {
  id: string;
  workflow_version_id: string;
  project_id: string;
  owner_id: string;
  profile: RenderProfile;
  status: "queued" | "composing" | "not_ready_to_compose" | "succeeded" | "failed";
  cache_key: string;
  manifest: null | {
    total_duration_seconds: number;
    composer_version: string;
    clips: ReadonlyArray<{
      scene_block_version_id: string;
      intent_ref?: string | null;
      animation_ir_ref?: string | null;
      compiled_program_ref?: string | null;
      artifact_sha256: string;
      duration_seconds: number;
      position: number;
    }>;
  };
  artifact_id: string | null;
  error_code: string | null;
  state_version: number;
  created_at: string;
};
