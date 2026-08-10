// Generated from Pydantic contracts. Do not edit.
export const CONTRACT_SCHEMA_VERSION = "1.6" as const;

export interface ApiErrorDetail {
  readonly code: string;
  readonly message: string;
  readonly stage?: PipelineStage | null;
}

export interface ApiErrorResponse {
  readonly error: ApiErrorDetail;
}

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

export interface ArtifactDescriptor {
  readonly id: string;
  readonly render_job_id: string;
  readonly kind: ArtifactKind;
  readonly sha256: string;
  readonly byte_size: number;
  readonly preview_url: string;
  readonly download_url: string;
}

export type ArtifactKind = "video" | "thumbnail" | "render_log" | "metadata";

export type AssumptionSource = "user" | "model" | "import" | "system";

export type AssumptionStatus = "proposed" | "accepted" | "rejected";

export type Audience = "primary_school" | "middle_school" | "high_school" | "undergraduate" | "general_audience";

export interface AuthenticatedUser {
  readonly id: string;
  readonly email: string;
  readonly must_change_password: boolean;
  readonly created_at: string;
}

export type ClarificationField = "audience" | "duration" | "derivation_style" | "assumptions" | "mathematical_intent";

export interface ClarificationQuestion {
  readonly field: ClarificationField;
  readonly question: string;
  readonly options?: ReadonlyArray<string>;
}

export type CodeGenerationCategory = "formula_derivation" | "function_visualization";

export type CodeGenerationErrorCode = "content_plan_not_found" | "provider_unavailable" | "provider_authentication" | "provider_configuration" | "provider_timeout" | "invalid_model_response" | "response_too_large" | "ast_parse_failed" | "static_policy_repairable" | "security_policy_violation" | "compile_failed" | "scene_structure_invalid" | "render_failed" | "sandbox_timeout" | "sandbox_resource_limit" | "attempt_budget_exhausted" | "category_degraded" | "generation_paused" | "internal_error";

export type CodeGenerationMode = "full" | "deterministic_template";

export type CodeGenerationOutcome = "ready" | "degraded" | "failed" | "paused";

export interface CodeGenerationRequest {
  readonly project_id: string;
  readonly owner_id: string;
  readonly prompt_version_id: string;
  readonly content_plan_version_id: string;
  readonly category: CodeGenerationCategory;
  readonly force_regenerate?: boolean;
}

export interface CodeGenerationResponse {
  readonly outcome: CodeGenerationOutcome;
  readonly code_version?: CodeVersion | null;
  readonly attempts_used: number;
  readonly mode: CodeGenerationMode;
  readonly error_code?: CodeGenerationErrorCode | null;
}

export interface CodeModelResponse {
  readonly scene_class: "GeneratedScene";
  readonly code: string;
  readonly assumptions?: ReadonlyArray<string>;
}

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
  readonly scene_class: string;
  readonly engine: "manimce";
  readonly engine_version: "0.20.1";
  readonly category?: CodeGenerationCategory;
  readonly generation_mode?: CodeGenerationMode;
  readonly prompt_template_version?: string | null;
  readonly provider_model?: string | null;
  readonly assumptions?: ReadonlyArray<string>;
}

export interface ContentPlanDraft {
  readonly schema_version: "1.1";
  readonly title: string;
  readonly audience: Audience;
  readonly language: Language;
  readonly target_duration_seconds: number;
  readonly derivation_style: DerivationStyle;
  readonly explicit_assumptions: ReadonlyArray<string>;
  readonly ambiguities: ReadonlyArray<string>;
  readonly scenes: ReadonlyArray<ContentPlanScene>;
}

export interface ContentPlanGenerationRequest {
  readonly project_id: string;
  readonly owner_id: string;
  readonly prompt_version_id: string;
  readonly audience?: Audience | null;
  readonly language?: Language;
  readonly target_duration_seconds?: number | null;
  readonly derivation_style?: DerivationStyle | null;
  readonly explicit_assumptions?: ReadonlyArray<string>;
}

export interface ContentPlanGenerationResponse {
  readonly outcome: ContentPlanOutcome;
  readonly content_plan_version?: ContentPlanVersion | null;
  readonly clarifications?: ReadonlyArray<ClarificationQuestion>;
  readonly limitations?: ReadonlyArray<ContentPlanLimitation>;
  readonly attempts_used: number;
}

export interface ContentPlanLimitation {
  readonly code: string;
  readonly message: string;
  readonly supported_alternative?: string | null;
}

export interface ContentPlanModelResponse {
  readonly outcome: ContentPlanOutcome;
  readonly plan?: ContentPlanDraft | null;
  readonly clarifications?: ReadonlyArray<ClarificationQuestion>;
  readonly limitations?: ReadonlyArray<ContentPlanLimitation>;
}

export type ContentPlanOutcome = "ready" | "needs_clarification" | "unsupported";

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
  readonly schema_version: "1.0" | "1.1";
  readonly title: string;
  readonly audience: Audience;
  readonly language: Language;
  readonly target_duration_seconds: number;
  readonly derivation_style?: DerivationStyle;
  readonly explicit_assumptions: ReadonlyArray<string>;
  readonly ambiguities?: ReadonlyArray<string>;
  readonly scenes: ReadonlyArray<ContentPlanScene>;
}

export interface ContentPlanVersionCreateRequest {
  readonly parent_version_id: string;
  readonly content_plan: ContentPlanDraft;
}

export interface ContentPlanVersionPage {
  readonly items: ReadonlyArray<ContentPlanVersion>;
  readonly next_cursor?: number | null;
}

export type DerivationStyle = "step_by_step" | "conceptual" | "proof_oriented" | "visual_intuition";

export interface Experiment {
  readonly id: string;
  readonly project_id: string;
  readonly owner_id: string;
  readonly title: string;
  readonly created_at: string;
  readonly archived_at?: string | null;
}

export interface ExperimentAssumption {
  readonly id: string;
  readonly statement: string;
  readonly source: AssumptionSource;
  readonly status: AssumptionStatus;
  readonly created_at: string;
}

export interface ExperimentCodeFile {
  readonly path: string;
  readonly language: "python";
  readonly content: string;
}

export interface ExperimentCreateRequest {
  readonly title: string;
  readonly domain_kind?: ExperimentDomainKind;
}

export type ExperimentDomainKind = "generic" | "geometry" | "ode" | "pde" | "fem" | "stochastic" | "optimization" | "neural_network" | "custom_python";

export interface ExperimentDraft {
  readonly experiment_id: string;
  readonly project_id: string;
  readonly owner_id: string;
  readonly revision: number;
  readonly model_spec: ModelSpec;
  readonly parameters: ReadonlyArray<ExperimentParameter>;
  readonly observables: ReadonlyArray<ExperimentObservable>;
  readonly assumptions: ReadonlyArray<ExperimentAssumption>;
  readonly visualization?: Readonly<Record<string, JsonValue>>;
  readonly code_files: ReadonlyArray<ExperimentCodeFile>;
  readonly updated_at: string;
}

export interface ExperimentDraftUpdateRequest {
  readonly expected_revision: number;
  readonly model_spec?: ModelSpec | null;
  readonly parameters?: ReadonlyArray<ExperimentParameter> | null;
  readonly observables?: ReadonlyArray<ExperimentObservable> | null;
  readonly assumptions?: ReadonlyArray<ExperimentAssumption> | null;
  readonly visualization?: Readonly<Record<string, JsonValue>> | null;
  readonly code_files?: ReadonlyArray<ExperimentCodeFile> | null;
}

export interface ExperimentObservable {
  readonly key: string;
  readonly label: string;
  readonly description?: string | null;
  readonly unit?: string | null;
}

export interface ExperimentPage {
  readonly items: ReadonlyArray<Experiment>;
  readonly next_cursor?: string | null;
}

export interface ExperimentParameter {
  readonly key: string;
  readonly label: string;
  readonly value: JsonValue;
  readonly unit?: string | null;
  readonly editable?: boolean;
}

export interface ExperimentPatchOperation {
  readonly operation: ExperimentPatchOperationKind;
  readonly path: string;
  readonly value?: JsonValue;
}

export type ExperimentPatchOperationKind = "add" | "replace" | "remove";

export interface ExperimentPatchProposal {
  readonly id: string;
  readonly experiment_id: string;
  readonly project_id: string;
  readonly owner_id: string;
  readonly expected_revision: number;
  readonly status: ExperimentPatchProposalStatus;
  readonly operations: ReadonlyArray<ExperimentPatchOperation>;
  readonly assumptions: ReadonlyArray<ExperimentAssumption>;
  readonly source: AssumptionSource;
  readonly created_at: string;
  readonly resolved_at?: string | null;
}

export interface ExperimentPatchProposalApplyRequest {
  readonly expected_revision: number;
}

export interface ExperimentPatchProposalPage {
  readonly items: ReadonlyArray<ExperimentPatchProposal>;
  readonly next_cursor?: string | null;
}

export interface ExperimentPatchProposalRejectRequest {
  readonly expected_revision: number;
  readonly reason?: string | null;
}

export type ExperimentPatchProposalStatus = "pending" | "applied" | "rejected";

export interface ExperimentVersion {
  readonly id: string;
  readonly project_id: string;
  readonly owner_id: string;
  readonly version: number;
  readonly parent_version_id: string | null;
  readonly created_at: string;
  readonly experiment_id: string;
  readonly draft_revision: number;
  readonly model_spec: ModelSpec;
  readonly parameters: ReadonlyArray<ExperimentParameter>;
  readonly observables: ReadonlyArray<ExperimentObservable>;
  readonly assumptions: ReadonlyArray<ExperimentAssumption>;
  readonly visualization?: Readonly<Record<string, JsonValue>>;
  readonly code_files: ReadonlyArray<ExperimentCodeFile>;
  readonly content_hash: string;
}

export interface ExperimentVersionCreateRequest {
  readonly expected_revision: number;
}

export interface ExperimentVersionPage {
  readonly items: ReadonlyArray<ExperimentVersion>;
  readonly next_cursor?: number | null;
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
  readonly provider_request_id?: string | null;
  readonly provider_model?: string | null;
  readonly prompt_tokens?: number | null;
  readonly completion_tokens?: number | null;
  readonly candidate_sha256?: string | null;
  readonly diagnostic_sha256?: string | null;
  readonly created_at: string;
}

export type GenerationStage = "content_plan" | "code" | "repair";

export type GenerationStatus = "started" | "succeeded" | "failed";

export interface JobEvent {
  readonly event_id: number;
  readonly render_job_id: string;
  readonly state_version: number;
  readonly stage: PipelineStage;
  readonly status: RenderJobStatus;
  readonly error_code?: string | null;
  readonly created_at: string;
}

export type JsonValue = string | boolean | number | ReadonlyArray<JsonValue> | Readonly<Record<string, JsonValue>> | null;

export type Language = "zh-CN" | "en-US";

export interface LoginRequest {
  readonly email: string;
  readonly password: string;
}

export interface LoginResponse {
  readonly user: AuthenticatedUser;
  readonly csrf_token: string;
  readonly expires_at: string;
}

export interface LogoutResponse {
  readonly ok: true;
}

export interface ModelSpec {
  readonly schema_version: "1.0";
  readonly domain_kind: ExperimentDomainKind;
  readonly plugin_id: string;
  readonly plugin_version: string;
  readonly payload: Readonly<Record<string, JsonValue>>;
}

export interface PasswordChangeRequest {
  readonly current_password: string;
  readonly new_password: string;
}

export type PipelineStage = "prompt" | "content_plan" | "code_generation" | "preview_render" | "final_render" | "artifact_delivery" | "quality_analysis" | "quality_recovery";

export interface Project {
  readonly id: string;
  readonly owner_id: string;
  readonly title: string;
  readonly created_at: string;
  readonly archived_at?: string | null;
}

export interface ProjectCreateRequest {
  readonly title: string;
}

export interface ProjectPage {
  readonly items: ReadonlyArray<Project>;
  readonly next_cursor?: string | null;
}

export interface ProjectUpdateRequest {
  readonly title?: string | null;
  readonly archived?: boolean | null;
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

export interface PromptVersionCreateRequest {
  readonly prompt: string;
}

export interface PromptVersionPage {
  readonly items: ReadonlyArray<PromptVersion>;
  readonly next_cursor?: number | null;
}

export interface QualityDiagnostic {
  readonly code: QualityDiagnosticCode;
  readonly severity: QualitySeverity;
  readonly stage: PipelineStage;
  readonly message: string;
  readonly suggestion: string;
  readonly evidence_ref?: string | null;
  readonly measured_value?: number | null;
  readonly threshold_value?: number | null;
}

export type QualityDiagnosticCode = "source_not_approved" | "default_play_duration_assumed" | "duration_too_short" | "duration_too_long" | "preview_final_timeline_mismatch" | "long_static_segment" | "blank_frame" | "object_out_of_bounds" | "object_overlap" | "text_too_small" | "cjk_glyph_missing" | "key_formula_missing" | "object_missing" | "animation_order_mismatch" | "timeline_unknown" | "terminal_wait_padding" | "media_metadata_invalid" | "media_metadata_inconsistent" | "planned_scene_missing";

export interface QualityHumanRatingRequest {
  readonly score: number;
  readonly notes?: string | null;
}

export interface QualityReport {
  readonly id: string;
  readonly project_id: string;
  readonly owner_id: string;
  readonly render_job_id: string;
  readonly code_version_id: string;
  readonly content_plan_version_id: string;
  readonly status: QualityStatus;
  readonly target_duration_seconds: number;
  readonly estimated_duration_seconds?: number | null;
  readonly actual_duration_seconds?: number | null;
  readonly frame_rate?: number | null;
  readonly frame_count?: number | null;
  readonly score?: number | null;
  readonly repair_count: number;
  readonly diagnostic_signature: string;
  readonly provider_model: string;
  readonly prompt_template_version: string;
  readonly content_plan_schema_version: string;
  readonly manim_version: string;
  readonly image_digest: string;
  readonly ast_policy_version: string;
  readonly diagnostic_policy_version: string;
  readonly created_at: string;
}

export interface QualityReportPage {
  readonly items: ReadonlyArray<QualityReport>;
  readonly next_cursor?: string | null;
}

export type QualitySeverity = "info" | "warning" | "error";

export type QualityStatus = "pending" | "analyzing" | "repair_required" | "repairing" | "passed" | "degraded" | "failed";

export interface RenderArtifactPayload {
  readonly kind: ArtifactKind;
  readonly relative_path: string;
  readonly sha256: string;
  readonly byte_size: number;
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
  readonly attempt_count?: number;
  readonly lease_owner?: string | null;
  readonly lease_token?: string | null;
  readonly lease_expires_at?: string | null;
  readonly heartbeat_at?: string | null;
  readonly cancellation_requested_at?: string | null;
  readonly state_version?: number;
}

export interface RenderJobCompletion {
  readonly lease_token: string;
  readonly artifacts: ReadonlyArray<RenderArtifactPayload>;
}

export type RenderJobFailureCode = "render_failed" | "sandbox_timeout" | "sandbox_oom" | "sandbox_pid_limit" | "sandbox_output_limit" | "sandbox_security_violation" | "artifact_publish_failed" | "lease_expired" | "runner_lost";

export interface RenderJobFailureReport {
  readonly lease_token: string;
  readonly failure_code: RenderJobFailureCode;
}

export interface RenderJobHeartbeat {
  readonly lease_token: string;
  readonly extend_seconds?: number;
}

export interface RenderJobLease {
  readonly job_id: string;
  readonly code_version_id: string;
  readonly content_plan_version_id: string;
  readonly target_duration_seconds: number;
  readonly profile: RenderProfile;
  readonly scene_class: string;
  readonly source_code: string;
  readonly source_sha256: string;
  readonly lease_token: string;
  readonly lease_expires_at: string;
  readonly attempt_number: number;
}

export interface RenderJobLeaseRequest {
  readonly runner_id: string;
  readonly lease_seconds?: number;
}

export type RenderJobStatus = "queued" | "claimed" | "running" | "succeeded" | "failed" | "cancelled";

export interface RenderJobSubmission {
  readonly project_id: string;
  readonly owner_id: string;
  readonly code_version_id: string;
  readonly profile: RenderProfile;
  readonly idempotency_key: string;
}

export type RenderProfile = "preview" | "final";

export interface User {
  readonly id: string;
  readonly email: string;
  readonly created_at: string;
}

export interface WorkspaceCodeGenerationRequest {
  readonly prompt_version_id: string;
  readonly content_plan_version_id: string;
  readonly category: CodeGenerationCategory;
  readonly force_regenerate?: boolean;
}

export interface WorkspaceContentPlanGenerationRequest {
  readonly prompt_version_id: string;
  readonly audience?: Audience | null;
  readonly language?: Language;
  readonly target_duration_seconds?: number | null;
  readonly derivation_style?: DerivationStyle | null;
  readonly explicit_assumptions?: ReadonlyArray<string>;
}

export interface WorkspaceRenderJobSubmission {
  readonly code_version_id: string;
  readonly profile: RenderProfile;
  readonly idempotency_key: string;
}
