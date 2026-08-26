// Generated from Pydantic contracts. Do not edit.
export const CONTRACT_SCHEMA_VERSION = "1.11" as const;

export interface AgentEvent {
  readonly stage: string;
  readonly status: "started" | "succeeded" | "failed" | "skipped";
  readonly message: string;
}

export type AgentRunOutcome = "ready" | "needs_confirmation" | "asset_required" | "unsupported" | "failed";

export interface AgentRunRequest {
  readonly prompt: string;
  readonly audience?: Audience;
  readonly language?: Language;
  readonly target_duration_seconds?: number;
  readonly csv_text?: string | null;
  readonly paper_text?: string | null;
  readonly project_id: string;
  readonly owner_id: string;
}

export interface AgentRunResponse {
  readonly outcome: AgentRunOutcome;
  readonly intent?: IntentSpec | null;
  readonly tool_runs?: ReadonlyArray<ToolRun>;
  readonly animation_ir?: AnimationIR | null;
  readonly events?: ReadonlyArray<AgentEvent>;
  readonly prompt_version?: PromptVersion | null;
  readonly content_plan_version?: ContentPlanVersion | null;
  readonly code_version?: CodeVersion | null;
  readonly error_code?: string | null;
  readonly message?: string | null;
  readonly critic_report?: CriticReport | null;
  readonly repair_count?: number;
}

export interface AnimAssertion {
  readonly type: AssertionType;
  readonly target?: string | null;
  readonly fields?: ReadonlyArray<string>;
}

export interface AnimBinding {
  readonly target: string;
  readonly source: BindingSource;
}

export interface AnimCameraOp {
  readonly op?: CameraOpKind;
  readonly target?: string | null;
  readonly rate?: number | null;
  readonly phi_degrees?: number | null;
  readonly theta_degrees?: number | null;
  readonly run_time?: number;
}

export interface AnimFallback {
  readonly on: string;
  readonly strategy: FallbackStrategy;
}

export interface AnimObject {
  readonly id: string;
  readonly type: ObjectType;
  readonly data_ref?: string | null;
  readonly text?: string | null;
  readonly color?: string | null;
}

export interface AnimationIR {
  readonly schema_version?: "2.0";
  readonly domain: string;
  readonly goal: string;
  readonly pattern: VisualPattern;
  readonly scene?: SceneHint;
  readonly data?: ReadonlyArray<DataRef>;
  readonly states?: ReadonlyArray<StateSpec>;
  readonly objects?: ReadonlyArray<AnimObject>;
  readonly bindings?: ReadonlyArray<AnimBinding>;
  readonly timeline: ReadonlyArray<TimelineOp>;
  readonly camera?: ReadonlyArray<AnimCameraOp>;
  readonly assertions?: ReadonlyArray<AnimAssertion>;
  readonly fallbacks?: ReadonlyArray<AnimFallback>;
}

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

export type AssertionType = "linear_superposition" | "harmonic_coefficients" | "gibbs_overshoot" | "trajectory_error" | "metric_match" | "data_fidelity" | "frenet_orthonormal" | "residual_matches_tool";

export type AssetDType = "float32" | "float64" | "int32" | "int64" | "uint8" | "bool";

export interface AssetField {
  readonly name: string;
  readonly dtype: AssetDType;
  readonly shape?: ReadonlyArray<number>;
}

export type AssetMime = "text/csv" | "application/x-npy" | "application/x-npz" | "text/plain" | "application/pdf";

export type AssetSource = "upload" | "tool_output";

export interface AssetVersion {
  readonly schema_version?: "1.0";
  readonly sha256: string;
  readonly mime: AssetMime;
  readonly size_bytes: number;
  readonly source: AssetSource;
  readonly columns: ReadonlyArray<string>;
  readonly fields: ReadonlyArray<AssetField>;
  readonly derived_from?: string | null;
}

export type Audience = "primary_school" | "middle_school" | "high_school" | "undergraduate" | "general_audience";

export interface AuthenticatedUser {
  readonly id: string;
  readonly email: string;
  readonly must_change_password: boolean;
  readonly created_at: string;
}

export type BindingOp = "sample" | "identity";

export interface BindingSource {
  readonly op?: BindingOp;
  readonly data?: string | null;
  readonly state?: string | null;
}

export interface BindingSpec {
  readonly object_id: string;
  readonly tracker_id: string;
  readonly expr_id?: IrExprId;
  readonly role?: string;
}

export interface CameraOp {
  readonly kind: IrCameraOpKind;
  readonly object_id?: string | null;
  readonly scale?: number | null;
  readonly phi_degrees?: number | null;
  readonly theta_degrees?: number | null;
  readonly rate?: number | null;
  readonly run_time?: number;
}

export type CameraOpKind = "static" | "follow" | "zoom" | "ambient_rotate" | "set_orientation";

export type ClarificationField = "audience" | "duration" | "derivation_style" | "assumptions" | "mathematical_intent";

export interface ClarificationQuestion {
  readonly field: ClarificationField;
  readonly question: string;
  readonly options?: ReadonlyArray<string>;
}

export type CodeGenerationCategory = "formula_derivation" | "function_visualization" | "plane_geometry" | "geometry_proof" | "three_d" | "mixed";

export type CodeGenerationErrorCode = "content_plan_not_found" | "provider_unavailable" | "provider_authentication" | "provider_configuration" | "provider_timeout" | "invalid_model_response" | "response_too_large" | "ast_parse_failed" | "static_policy_repairable" | "security_policy_violation" | "compile_failed" | "scene_structure_invalid" | "render_failed" | "sandbox_timeout" | "sandbox_resource_limit" | "attempt_budget_exhausted" | "category_degraded" | "generation_paused" | "internal_error";

export type CodeGenerationMode = "full" | "deterministic_template" | "compiled_ir";

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
  readonly engine_version: "0.21.0";
  readonly category?: CodeGenerationCategory;
  readonly generation_mode?: CodeGenerationMode;
  readonly prompt_template_version?: string | null;
  readonly provider_model?: string | null;
  readonly assumptions?: ReadonlyArray<string>;
}

export interface CompositionManifest {
  readonly workflow_version_id: string;
  readonly profile: RenderProfile;
  readonly clips: ReadonlyArray<CompositionManifestClip>;
  readonly total_duration_seconds: number;
  readonly composer_version: string;
}

export interface CompositionManifestClip {
  readonly scene_block_version_id: string;
  readonly artifact_sha256: string;
  readonly duration_seconds: number;
  readonly position: number;
}

export interface CompositionRun {
  readonly id: string;
  readonly workflow_version_id: string;
  readonly project_id: string;
  readonly owner_id: string;
  readonly profile: RenderProfile;
  readonly status: CompositionRunStatus;
  readonly cache_key: string;
  readonly manifest?: CompositionManifest | null;
  readonly artifact_id?: string | null;
  readonly error_code?: string | null;
  readonly state_version?: number;
  readonly created_at: string;
}

export type CompositionRunStatus = "queued" | "composing" | "not_ready_to_compose" | "succeeded" | "failed";

export interface ContentPlanDraft {
  readonly schema_version: "1.1" | "1.6";
  readonly title: string;
  readonly audience: Audience;
  readonly language: Language;
  readonly target_duration_seconds: number;
  readonly derivation_style: DerivationStyle;
  readonly explicit_assumptions: ReadonlyArray<string>;
  readonly ambiguities: ReadonlyArray<string>;
  readonly scenes: ReadonlyArray<ContentPlanScene>;
  readonly storyboard?: SceneStoryboard | null;
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
  readonly formula_steps?: ReadonlyArray<FormulaStep>;
  readonly visual_intent: string;
  readonly narration_placeholder: string;
  readonly visual_kind?: VisualKind | null;
}

export interface ContentPlanVersion {
  readonly id: string;
  readonly project_id: string;
  readonly owner_id: string;
  readonly version: number;
  readonly parent_version_id: string | null;
  readonly created_at: string;
  readonly schema_version: "1.0" | "1.1" | "1.6";
  readonly title: string;
  readonly audience: Audience;
  readonly language: Language;
  readonly target_duration_seconds: number;
  readonly derivation_style?: DerivationStyle;
  readonly explicit_assumptions: ReadonlyArray<string>;
  readonly ambiguities?: ReadonlyArray<string>;
  readonly scenes: ReadonlyArray<ContentPlanScene>;
  readonly storyboard?: SceneStoryboard | null;
}

export interface ContentPlanVersionCreateRequest {
  readonly parent_version_id: string;
  readonly content_plan: ContentPlanDraft;
}

export interface ContentPlanVersionPage {
  readonly items: ReadonlyArray<ContentPlanVersion>;
  readonly next_cursor?: number | null;
}

export type CriticAnswer = "yes" | "no";

export interface CriticFinding {
  readonly code: string;
  readonly message: string;
  readonly repairable?: boolean;
}

export interface CriticQuestionResult {
  readonly id: string;
  readonly question: string;
  readonly answer: CriticAnswer;
  readonly expected?: CriticAnswer;
  readonly evidence?: "ir" | "source" | "tool" | "vlm";
}

export interface CriticReport {
  readonly schema_version?: "1.0";
  readonly expression_score: number;
  readonly vlm_used?: boolean;
  readonly questions?: ReadonlyArray<CriticQuestionResult>;
  readonly findings?: ReadonlyArray<CriticFinding>;
}

export type DataKind = "array" | "series" | "trajectory" | "trajectory_set" | "table";

export interface DataRef {
  readonly id: string;
  readonly kind: DataKind;
  readonly artifact_ref: string;
  readonly output_sha256?: string | null;
}

export type DerivationStyle = "step_by_step" | "conceptual" | "proof_oriented" | "visual_intuition";

export type FallbackStrategy = "static_frame" | "discrete_samples" | "fixed_camera" | "precomputed_only";

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

export interface GeometryConstruction {
  readonly object_id: string;
  readonly kind: IrObjectType;
  readonly label?: string | null;
}

export interface GeometryProofRating {
  readonly given_complete: boolean;
  readonly prove_matches: boolean;
  readonly math_correct: number;
  readonly visual_clear: number;
  readonly notes?: string | null;
}

export interface GlobalBrief {
  readonly title: string;
  readonly language: Language;
  readonly target_duration_seconds: number;
  readonly aspect_ratio?: "16:9";
  readonly style_preset: WorkflowStylePreset;
  readonly background: string;
  readonly palette: ReadonlyArray<string>;
  readonly notation?: Readonly<Record<string, string>>;
  readonly scientific_parameters?: Readonly<Record<string, number>>;
}

export type IntentDomain = "physics.wave" | "math.signal" | "dynamical_systems" | "control" | "data_analysis" | "geometry.diff3d" | "scientific_reproduction" | "teaching";

export interface IntentSpec {
  readonly schema_version?: "1.0";
  readonly domain: IntentDomain;
  readonly goal: string;
  readonly assumptions?: ReadonlyArray<string>;
  readonly tools_needed?: ReadonlyArray<ToolNeed>;
  readonly output_duration_seconds?: number;
  readonly dimension?: "2d" | "3d";
  readonly needs_confirmation?: boolean;
  readonly asset_required?: boolean;
  readonly asset_kind?: string | null;
  readonly category_hint?: CodeGenerationCategory;
}

export type IrCameraOpKind = "zoom_to" | "restore_frame" | "set_orientation" | "ambient_rotate";

export type IrExprId = "identity" | "pow2" | "pow3" | "cubic_slope" | "sine" | "linear" | "secant_slope";

export type IrObjectType = "title" | "math_tex" | "text" | "axes" | "plot" | "dot" | "line" | "dashed_line" | "circle" | "polygon" | "angle" | "right_angle" | "label" | "decimal" | "surface" | "sphere" | "cube" | "image_ref" | "equation_panel" | "geometry_figure";

export type IrStateChangeKind = "set_value" | "transform_matching_tex" | "lagged_start" | "succession" | "animation_group" | "fade_in" | "create" | "wait" | "write" | "indicate";

export interface JobEvent {
  readonly event_id: number;
  readonly render_job_id: string;
  readonly state_version: number;
  readonly stage: PipelineStage;
  readonly status: RenderJobStatus;
  readonly error_code?: string | null;
  readonly created_at: string;
}

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

export type ObjectType = "title" | "scalar_field" | "graph" | "point" | "path" | "trajectory_set" | "timeseries" | "region" | "arrow_frame" | "numeric_panel";

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

export interface ProofStep {
  readonly statement: string;
  readonly reason: string;
  readonly object_ids?: ReadonlyArray<string>;
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
  readonly code_version_id?: string | null;
  readonly program_render_segment_id?: string | null;
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
  readonly concat_group_id?: string | null;
  readonly segment_index?: number | null;
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
  readonly code_version_id?: string | null;
  readonly program_render_segment_id?: string | null;
  readonly content_plan_version_id?: string | null;
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
  readonly code_version_id?: string | null;
  readonly program_render_segment_id?: string | null;
  readonly profile: RenderProfile;
  readonly idempotency_key: string;
  readonly concat_group_id?: string | null;
  readonly segment_index?: number | null;
}

export type RenderProfile = "preview" | "final";

export interface SceneBlockRun {
  readonly id: string;
  readonly project_id: string;
  readonly owner_id: string;
  readonly scene_block_version_id: string;
  readonly status: SceneBlockRunStatus;
  readonly pipeline_used?: ScenePipeline | null;
  readonly intent_ref?: string | null;
  readonly animation_ir_ref?: string | null;
  readonly compiled_program_ref?: string | null;
  readonly preview_artifact_id?: string | null;
  readonly final_artifact_id?: string | null;
  readonly cache_key: string;
  readonly error_code?: string | null;
  readonly state_version?: number;
  readonly created_at: string;
}

export type SceneBlockRunStatus = "queued" | "planning" | "needs_confirmation" | "asset_required" | "compiling" | "rendering" | "succeeded" | "failed";

export interface SceneBlockVersion {
  readonly id: string;
  readonly project_id: string;
  readonly workflow_id: string;
  readonly owner_id: string;
  readonly version: number;
  readonly parent_version_id: string | null;
  readonly title: string;
  readonly prompt: string;
  readonly pipeline_mode: ScenePipelineMode;
  readonly target_duration_seconds: number;
  readonly asset_version_ids?: ReadonlyArray<string>;
  readonly created_at: string;
}

export interface SceneHint {
  readonly dimension?: "2d" | "3d";
  readonly renderer_hint?: "manim" | "web";
}

export interface SceneObject {
  readonly id: string;
  readonly type: IrObjectType;
  readonly text?: string | null;
  readonly color?: string | null;
  readonly x?: number | null;
  readonly y?: number | null;
  readonly z?: number | null;
  readonly radius?: number | null;
  readonly vertices?: ReadonlyArray<readonly [number, number]>;
  readonly asset_sha256?: string | null;
  readonly parent_id?: string | null;
  readonly formula?: string | null;
}

export type ScenePipeline = "teaching" | "scientific";

export type ScenePipelineMode = "auto" | "teaching" | "scientific";

export interface SceneStep {
  readonly goal: string;
  readonly duration_seconds: number;
  readonly visual_kind: VisualKind;
  readonly objects?: ReadonlyArray<SceneObject>;
  readonly trackers?: ReadonlyArray<TrackerSpec>;
  readonly bindings?: ReadonlyArray<BindingSpec>;
  readonly state_changes?: ReadonlyArray<StateChange>;
  readonly camera?: ReadonlyArray<CameraOp>;
  readonly given?: ReadonlyArray<string>;
  readonly prove?: string | null;
  readonly proof_steps?: ReadonlyArray<ProofStep>;
  readonly constructions?: ReadonlyArray<GeometryConstruction>;
}

export interface SceneStoryboard {
  readonly target_duration_seconds: number;
  readonly steps: ReadonlyArray<SceneStep>;
}

export interface StateChange {
  readonly kind: IrStateChangeKind;
  readonly target_ids?: ReadonlyArray<string>;
  readonly tracker_id?: string | null;
  readonly value?: number | null;
  readonly from_text?: string | null;
  readonly to_text?: string | null;
  readonly run_time?: number;
  readonly lag_ratio?: number;
  readonly wait_time?: number;
}

export interface StateSpec {
  readonly id: string;
  readonly type?: StateType;
  readonly initial?: number;
  readonly range?: readonly [number, number] | null;
}

export type StateType = "scalar" | "integer";

export interface TimelineOp {
  readonly op: TimelineOpKind;
  readonly target?: string | null;
  readonly targets?: ReadonlyArray<string>;
  readonly duration?: number;
  readonly to?: number | null;
  readonly wait_time?: number;
}

export type TimelineOpKind = "create" | "animate_state" | "trace" | "compare" | "highlight" | "reveal" | "wait";

export interface ToolNeed {
  readonly op: ToolOp;
  readonly params?: Readonly<Record<string, number | number | string | boolean>>;
}

export type ToolOp = "wave2d_superposition" | "fourier_square_wave" | "lorenz_ensemble" | "pid_step_response" | "csv_anomaly" | "frenet_frame" | "ode_compare";

export interface ToolRun {
  readonly id: string;
  readonly op: ToolOp;
  readonly params_sha256: string;
  readonly input_sha256: string;
  readonly output_sha256: string;
  readonly artifact_ref: string;
  readonly artifact_path: string;
  readonly assertions?: Readonly<Record<string, number | number | boolean | string>>;
  readonly asset_version?: AssetVersion | null;
  readonly input_asset_version?: AssetVersion | null;
}

export interface TrackerSpec {
  readonly id: string;
  readonly initial: number;
  readonly minimum?: number | null;
  readonly maximum?: number | null;
}

export interface User {
  readonly id: string;
  readonly email: string;
  readonly created_at: string;
}

export interface UserAsset {
  readonly id: string;
  readonly project_id: string;
  readonly owner_id: string;
  readonly kind: UserAssetKind;
  readonly sha256: string;
  readonly byte_size: number;
  readonly content_type: string;
  readonly original_filename: string;
}

export type UserAssetKind = "image" | "construction_json";

export interface VideoWorkflowVersion {
  readonly id: string;
  readonly workflow_id: string;
  readonly project_id: string;
  readonly owner_id: string;
  readonly version: number;
  readonly parent_version_id: string | null;
  readonly global_brief: GlobalBrief;
  readonly nodes: ReadonlyArray<WorkflowNode>;
  readonly edges: ReadonlyArray<WorkflowEdge>;
  readonly created_at: string;
}

export type VisualKind = "formula" | "function" | "plane_geometry" | "geometry_proof" | "three_d";

export type VisualPattern = "field_evolution" | "formula_morph" | "trajectory_trace" | "3d_orbit" | "comparison" | "data_anomaly";

export interface WorkflowEdge {
  readonly source_node_id: string;
  readonly target_node_id: string;
}

export interface WorkflowNode {
  readonly id: string;
  readonly kind: WorkflowNodeKind;
  readonly scene_block_version_id?: string | null;
}

export type WorkflowNodeKind = "scene" | "compose" | "export";

export type WorkflowStylePreset = "dark_scientific" | "light_academic" | "minimal_math" | "presentation";

export interface WorkspaceAgentRunRequest {
  readonly prompt: string;
  readonly audience?: Audience;
  readonly language?: Language;
  readonly target_duration_seconds?: number;
  readonly csv_text?: string | null;
  readonly paper_text?: string | null;
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
