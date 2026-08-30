import type {
  AgentRunResponse,
  ApiErrorResponse,
  ArtifactDescriptor,
  CodeGenerationResponse,
  ContentPlanGenerationResponse,
  ContentPlanVersion,
  ContentPlanVersionCreateRequest,
  ContentPlanVersionPage,
  DirectorDraft,
  DirectorPlan,
  LoginRequest,
  LoginResponse,
  PasswordChangeRequest,
  Project,
  ProjectCreateRequest,
  ProjectPage,
  ProjectUpdateRequest,
  PromptVersion,
  PromptVersionCreateRequest,
  PromptVersionPage,
  QualityDiagnostic,
  QualityHumanRatingRequest,
  QualityReport,
  QualityReportPage,
  RenderJob,
  SceneRunProvenance,
  WorkspaceAgentRunRequest,
  WorkspaceCodeGenerationRequest,
  WorkspaceContentPlanGenerationRequest,
  WorkspaceRenderJobSubmission,
} from "@manim-workbench/contracts";
import type {
  CompositionRun,
  GlobalBrief,
  RenderProfile,
  SceneBlockRun,
  SceneBlockVersion,
  ScenePipelineMode,
  VideoWorkflow,
  VideoWorkflowVersion,
  WorkflowEdge,
  WorkflowNode,
} from "../../components/workflow/types";

const DEFAULT_API_ORIGIN = "";

export function createIdempotencyKey(): string {
  const randomUUID = globalThis.crypto?.randomUUID;
  if (randomUUID) return randomUUID.call(globalThis.crypto);
  return `fallback-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export class ApiClientError extends Error {
  readonly status: number;
  readonly code: string;
  readonly stage: string | null;

  constructor(status: number, payload: ApiErrorResponse) {
    super(payload.error.message);
    this.name = "ApiClientError";
    this.status = status;
    this.code = payload.error.code;
    this.stage = payload.error.stage ?? null;
  }
}

export class WorkbenchApiClient {
  readonly baseUrl: string;
  #csrfToken: string | null = null;

  constructor(baseUrl = DEFAULT_API_ORIGIN) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  get csrfTokenAvailable(): boolean {
    return this.#csrfToken !== null;
  }

  async login(input: LoginRequest): Promise<LoginResponse> {
    const response = await this.#request<LoginResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(input),
    }, false);
    this.#csrfToken = response.csrf_token;
    return response;
  }

  async session(): Promise<LoginResponse> {
    const response = await this.#request<LoginResponse>("/api/v1/auth/session", {}, false);
    this.#csrfToken = response.csrf_token;
    return response;
  }

  async changePassword(input: PasswordChangeRequest): Promise<LoginResponse> {
    const response = await this.#request<LoginResponse>("/api/v1/auth/change-password", {
      method: "POST",
      body: JSON.stringify(input),
    });
    this.#csrfToken = response.csrf_token;
    return response;
  }

  async logout(): Promise<void> {
    await this.#request("/api/v1/auth/logout", { method: "POST" });
    this.#csrfToken = null;
  }

  listProjects(cursor?: string, limit = 20): Promise<ProjectPage> {
    const query = new URLSearchParams({ limit: String(limit) });
    if (cursor) query.set("cursor", cursor);
    return this.#request(`/api/v1/projects?${query}`);
  }

  createProject(input: ProjectCreateRequest): Promise<Project> {
    return this.#jsonMutation("/api/v1/projects", "POST", input);
  }

  updateProject(projectId: string, input: ProjectUpdateRequest): Promise<Project> {
    return this.#jsonMutation(`/api/v1/projects/${projectId}`, "PATCH", input);
  }

  listPromptVersions(projectId: string, cursor?: number, limit = 20): Promise<PromptVersionPage> {
    const query = new URLSearchParams({ limit: String(limit) });
    if (cursor) query.set("cursor", String(cursor));
    return this.#request(`/api/v1/projects/${projectId}/prompt-versions?${query}`);
  }

  createPromptVersion(
    projectId: string,
    input: PromptVersionCreateRequest,
  ): Promise<PromptVersion> {
    return this.#jsonMutation(`/api/v1/projects/${projectId}/prompt-versions`, "POST", input);
  }

  listContentPlanVersions(
    projectId: string,
    cursor?: number,
    limit = 20,
  ): Promise<ContentPlanVersionPage> {
    const query = new URLSearchParams({ limit: String(limit) });
    if (cursor) query.set("cursor", String(cursor));
    return this.#request(`/api/v1/projects/${projectId}/content-plan-versions?${query}`);
  }

  saveContentPlanVersion(
    projectId: string,
    input: ContentPlanVersionCreateRequest,
  ): Promise<ContentPlanVersion> {
    return this.#jsonMutation(
      `/api/v1/projects/${projectId}/content-plan-versions`,
      "POST",
      input,
    );
  }

  generateContentPlan(
    projectId: string,
    input: WorkspaceContentPlanGenerationRequest,
  ): Promise<ContentPlanGenerationResponse> {
    return this.#jsonMutation(
      `/api/v1/workspace/projects/${projectId}/content-plans/generate`,
      "POST",
      input,
    );
  }

  generateCode(
    projectId: string,
    input: WorkspaceCodeGenerationRequest,
  ): Promise<CodeGenerationResponse> {
    return this.#jsonMutation(
      `/api/v1/workspace/projects/${projectId}/code-generations`,
      "POST",
      input,
    );
  }

  runAgent(projectId: string, input: WorkspaceAgentRunRequest): Promise<AgentRunResponse> {
    return this.#jsonMutation(
      `/api/v1/workspace/projects/${projectId}/agent-runs`,
      "POST",
      input,
    );
  }

  submitRenderJob(projectId: string, input: WorkspaceRenderJobSubmission): Promise<RenderJob> {
    return this.#jsonMutation(
      `/api/v1/workspace/projects/${projectId}/render-jobs`,
      "POST",
      input,
    );
  }

  getRenderJob(jobId: string): Promise<RenderJob> {
    return this.#request(`/api/v1/workspace/render-jobs/${jobId}`);
  }

  cancelRenderJob(jobId: string): Promise<RenderJob> {
    return this.#request(`/api/v1/workspace/render-jobs/${jobId}/cancel`, { method: "POST" });
  }

  listArtifacts(jobId: string): Promise<ReadonlyArray<ArtifactDescriptor>> {
    return this.#request(`/api/v1/workspace/render-jobs/${jobId}/artifacts`);
  }

  getQualityReport(reportId: string): Promise<QualityReport> {
    return this.#request(`/api/v1/quality-reports/${reportId}`);
  }

  listQualityDiagnostics(reportId: string): Promise<ReadonlyArray<QualityDiagnostic>> {
    return this.#request(`/api/v1/quality-reports/${reportId}/diagnostics`);
  }

  listProjectQualityReports(
    projectId: string,
    cursor?: string,
    limit = 20,
  ): Promise<QualityReportPage> {
    const query = new URLSearchParams({ limit: String(limit) });
    if (cursor) query.set("cursor", cursor);
    return this.#request(`/api/v1/projects/${projectId}/quality-reports?${query}`);
  }

  getJobQualityReport(jobId: string): Promise<QualityReport> {
    return this.#request(`/api/v1/render-jobs/${jobId}/quality-report`);
  }

  rateQualityReport(reportId: string, input: QualityHumanRatingRequest): Promise<void> {
    return this.#jsonMutation(`/api/v1/quality-reports/${reportId}/human-rating`, "POST", input);
  }

  eventUrl(jobId: string): string {
    return `${this.baseUrl}/api/v1/render-jobs/${jobId}/events`;
  }

  artifactUrl(artifactId: string, download = false): string {
    return `${this.baseUrl}/api/v1/artifacts/${artifactId}${download ? "/download" : ""}`;
  }

  codeSourceUrl(codeVersionId: string, download = false): string {
    const query = download ? "?download=true" : "";
    return `${this.baseUrl}/api/v1/workspace/code-versions/${codeVersionId}/source${query}`;
  }

  createVideoWorkflow(projectId: string): Promise<VideoWorkflow> {
    return this.#request(`/api/v1/projects/${projectId}/video-workflows`, { method: "POST" });
  }

  createDirectorPlan(projectId: string, input: {
    objective: string;
    title?: string | null;
    language: "zh-CN" | "en-US";
    target_duration_seconds: number;
    style_preset?: string | null;
    asset_version_ids: ReadonlyArray<string>;
    idempotency_key: string;
  }): Promise<DirectorPlan> {
    return this.#jsonMutation(`/api/v1/projects/${projectId}/director-plans`, "POST", input);
  }

  getDirectorPlan(projectId: string, planId: string): Promise<DirectorPlan> {
    return this.#request(`/api/v1/projects/${projectId}/director-plans/${planId}`);
  }

  applyDirectorPlan(projectId: string, planId: string, input: {
    draft: DirectorDraft;
    scene_asset_version_ids: ReadonlyArray<ReadonlyArray<string>>;
    idempotency_key: string;
  }): Promise<VideoWorkflowVersion> {
    return this.#jsonMutation(
      `/api/v1/projects/${projectId}/director-plans/${planId}/apply`,
      "POST",
      input,
    );
  }

  createScientificCsvAsset(projectId: string, csvText: string): Promise<{
    id: string;
    sha256: string;
    mime: string;
    size_bytes: number;
  }> {
    return this.#jsonMutation(
      `/api/v1/projects/${projectId}/scientific-assets/csv`,
      "POST",
      { csv_text: csvText },
    );
  }

  getVideoWorkflow(workflowId: string): Promise<VideoWorkflow> {
    return this.#request(`/api/v1/video-workflows/${workflowId}`);
  }

  createSceneBlock(workflowId: string, input: {
    title: string;
    prompt: string;
    pipeline_mode: ScenePipelineMode;
    target_duration_seconds: number;
    asset_version_ids: ReadonlyArray<string>;
  }): Promise<{ block: { id: string }; version: SceneBlockVersion }> {
    return this.#jsonMutation(
      `/api/v1/video-workflows/${workflowId}/scene-blocks`,
      "POST",
      input,
    );
  }

  createSceneBlockVersion(blockId: string, input: {
    parent_version_id: string;
    title: string;
    prompt: string;
    pipeline_mode: ScenePipelineMode;
    target_duration_seconds: number;
    asset_version_ids: ReadonlyArray<string>;
  }): Promise<SceneBlockVersion> {
    return this.#jsonMutation(`/api/v1/scene-blocks/${blockId}/versions`, "POST", input);
  }

  getSceneBlockVersion(versionId: string): Promise<{
    block_id: string;
    version: SceneBlockVersion;
  }> {
    return this.#request(`/api/v1/scene-block-versions/${versionId}`);
  }

  createVideoWorkflowVersion(workflowId: string, input: {
    parent_version_id: string | null;
    global_brief: GlobalBrief;
    nodes: ReadonlyArray<WorkflowNode>;
    edges: ReadonlyArray<WorkflowEdge>;
  }): Promise<VideoWorkflowVersion> {
    return this.#jsonMutation(`/api/v1/video-workflows/${workflowId}/versions`, "POST", input);
  }

  getVideoWorkflowVersion(versionId: string): Promise<VideoWorkflowVersion> {
    return this.#request(`/api/v1/workflow-versions/${versionId}`);
  }

  submitSceneBlockRun(
    versionId: string,
    input: { workflow_version_id: string; profile: RenderProfile; idempotency_key: string },
  ): Promise<SceneBlockRun> {
    return this.#jsonMutation(`/api/v1/scene-block-versions/${versionId}/runs`, "POST", input);
  }

  getSceneBlockRun(runId: string): Promise<SceneBlockRun> {
    return this.#request(`/api/v1/scene-block-runs/${runId}`);
  }

  getSceneRunProvenance(runId: string): Promise<SceneRunProvenance> {
    return this.#request(`/api/v1/scene-block-runs/${runId}/provenance`);
  }

  submitCompositionRun(
    versionId: string,
    input: { profile: RenderProfile; idempotency_key: string },
  ): Promise<CompositionRun> {
    return this.#jsonMutation(
      `/api/v1/workflow-versions/${versionId}/composition-runs`,
      "POST",
      input,
    );
  }

  getCompositionRun(runId: string): Promise<CompositionRun> {
    return this.#request(`/api/v1/composition-runs/${runId}`);
  }

  compositionArtifactUrl(runId: string): string {
    return `${this.baseUrl}/api/v1/composition-runs/${runId}/artifact`;
  }

  async getCodeSource(codeVersionId: string): Promise<string> {
    const response = await fetch(this.codeSourceUrl(codeVersionId), {
      credentials: "include",
      cache: "no-store",
    });
    if (!response.ok) {
      const payload = (await response.json()) as ApiErrorResponse;
      throw new ApiClientError(response.status, payload);
    }
    return response.text();
  }

  async #jsonMutation<T>(path: string, method: "POST" | "PATCH", input: object): Promise<T> {
    return this.#request<T>(path, { method, body: JSON.stringify(input) });
  }

  async #request<T = void>(
    path: string,
    init: RequestInit = {},
    csrfRequired = true,
  ): Promise<T> {
    const headers = new Headers(init.headers);
    if (init.body) headers.set("Content-Type", "application/json");
    if (csrfRequired && init.method && init.method !== "GET") {
      if (!this.#csrfToken) throw new Error("A hydrated session is required for this action.");
      headers.set("X-CSRF-Token", this.#csrfToken);
    }
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers,
      credentials: "include",
      cache: "no-store",
    });
    if (!response.ok) {
      const payload = (await response.json()) as ApiErrorResponse;
      throw new ApiClientError(response.status, payload);
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }
}

export const workbenchApi = new WorkbenchApiClient();
