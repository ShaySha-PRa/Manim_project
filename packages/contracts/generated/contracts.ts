// Generated from Pydantic contracts. Do not edit.
export const CONTRACT_SCHEMA_VERSION = "1.0" as const;

export interface Artifact {
  readonly id: string;
  readonly project_id: string;
  readonly owner_id: string;
  readonly render_job_id: string;
  readonly kind: ArtifactKind;
  readonly relative_path: string;
  readonly sha256: string;
  readonly byte_size: number;
  readonly created_at: string;
}

export type ArtifactKind = "video" | "thumbnail" | "render_log" | "metadata";

export type Audience = "primary_school" | "middle_school" | "high_school" | "undergraduate";

export interface CodeVersion {
  readonly id: string;
  readonly project_id: string;
  readonly owner_id: string;
  readonly version: number;
  readonly parent_version_id: string | null;
  readonly created_at: string;
  readonly prompt_version_id: string;
  readonly content_plan_version_id: string;
  readonly source_code: string;
  readonly source_sha256: string;
  readonly engine: "manimce";
  readonly engine_version: "0.20.1";
}

export interface ContentPlanScene {
  readonly scene_number: number;
  readonly teaching_goal: string;
  readonly formula_steps: ReadonlyArray<FormulaStep>;
  readonly visual_intent: string;
  readonly narration_placeholder: string;
}

export interface ContentPlanVersion {
  readonly id: string;
  readonly project_id: string;
  readonly owner_id: string;
  readonly version: number;
  readonly parent_version_id: string | null;
  readonly created_at: string;
  readonly schema_version: "1.0";
  readonly title: string;
  readonly audience: Audience;
  readonly language: Language;
  readonly target_duration_seconds: number;
  readonly explicit_assumptions: ReadonlyArray<string>;
  readonly scenes: ReadonlyArray<ContentPlanScene>;
}

export interface FormulaStep {
  readonly expression: string;
  readonly explanation: string;
}

export interface GenerationAttempt {
  readonly id: string;
  readonly project_id: string;
  readonly owner_id: string;
  readonly stage: GenerationStage;
  readonly attempt_number: number;
  readonly status: GenerationStatus;
  readonly input_version_id: string;
  readonly output_version_id?: string | null;
  readonly error_code?: string | null;
  readonly created_at: string;
}

export type GenerationStage = "content_plan" | "code" | "repair";

export type GenerationStatus = "started" | "succeeded" | "failed";

export type Language = "zh-CN" | "en-US";

export interface Project {
  readonly id: string;
  readonly owner_id: string;
  readonly title: string;
  readonly created_at: string;
  readonly archived_at?: string | null;
}

export interface PromptVersion {
  readonly id: string;
  readonly project_id: string;
  readonly owner_id: string;
  readonly version: number;
  readonly parent_version_id: string | null;
  readonly created_at: string;
  readonly prompt: string;
}

export interface RenderJob {
  readonly id: string;
  readonly project_id: string;
  readonly owner_id: string;
  readonly code_version_id: string;
  readonly profile: RenderProfile;
  readonly status: RenderJobStatus;
  readonly idempotency_key: string;
  readonly created_at: string;
  readonly started_at?: string | null;
  readonly finished_at?: string | null;
  readonly failure_code?: string | null;
}

export type RenderJobStatus = "queued" | "claimed" | "running" | "succeeded" | "failed" | "cancelled";

export type RenderProfile = "preview" | "final";

export interface User {
  readonly id: string;
  readonly email: string;
  readonly created_at: string;
}
