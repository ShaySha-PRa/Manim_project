import json
from pathlib import Path

from manim_workbench_contracts.generation import render_contract_artifacts

ROOT = Path(__file__).resolve().parents[2]
GENERATED = ROOT / "packages" / "contracts" / "generated"


def test_generated_contracts_are_in_sync() -> None:
    expected_schema, expected_typescript = render_contract_artifacts()

    assert (GENERATED / "contracts.schema.json").read_text(encoding="utf-8") == expected_schema
    assert (GENERATED / "contracts.ts").read_text(encoding="utf-8") == expected_typescript


def test_generated_schema_forbids_unconstrained_escape_hatches() -> None:
    schema_text = (GENERATED / "contracts.schema.json").read_text(encoding="utf-8")
    schema = json.loads(schema_text)

    assert "additionalProperties" in schema_text
    assert '"additionalProperties": true' not in schema_text
    assert '"other"' not in schema_text.lower()
    assert set(schema["x-contract-models"]) == {
        "AgentEvent",
        "AgentRunRequest",
        "AgentRunResponse",
        "AnimAssertion",
        "AnimBinding",
        "AnimCameraOp",
        "AnimFallback",
        "AnimObject",
        "AnimationIR",
        "ApiErrorDetail",
        "ApiErrorResponse",
        "Artifact",
        "ArtifactDescriptor",
        "AssetField",
        "AssetVersion",
        "AuthenticatedUser",
        "BindingSource",
        "BindingSpec",
        "CameraOp",
        "ClarificationQuestion",
        "CodeGenerationRequest",
        "CodeGenerationResponse",
        "CodeModelResponse",
        "CodeVersion",
        "ContentPlanDraft",
        "ContentPlanGenerationRequest",
        "ContentPlanGenerationResponse",
        "ContentPlanLimitation",
        "ContentPlanModelResponse",
        "ContentPlanVersion",
        "ContentPlanVersionCreateRequest",
        "ContentPlanVersionPage",
        "CompositionManifest",
        "CompositionManifestClip",
        "CompositionRun",
        "CriticFinding",
        "CriticQuestionResult",
        "CriticReport",
        "DataRef",
        "GenerationAttempt",
        "GeometryConstruction",
        "GeometryProofRating",
        "GlobalBrief",
        "IntentSpec",
        "JobEvent",
        "LoginRequest",
        "LoginResponse",
        "LogoutResponse",
        "PasswordChangeRequest",
        "Project",
        "ProjectCreateRequest",
        "ProjectPage",
        "ProjectUpdateRequest",
        "PromptVersion",
        "PromptVersionCreateRequest",
        "PromptVersionPage",
        "ProofStep",
        "QualityDiagnostic",
        "QualityHumanRatingRequest",
        "QualityReport",
        "QualityReportPage",
        "RenderArtifactPayload",
        "RenderJob",
        "RenderJobCompletion",
        "RenderJobFailureReport",
        "RenderJobHeartbeat",
        "RenderJobLease",
        "RenderJobLeaseRequest",
        "RenderJobSubmission",
        "SceneHint",
        "SceneBlockRun",
        "SceneBlockVersion",
        "SceneRunProvenance",
        "SceneObject",
        "SceneStep",
        "SceneStoryboard",
        "StateChange",
        "StateSpec",
        "TimelineOp",
        "ToolNeed",
        "ToolRun",
        "TrackerSpec",
        "User",
        "UserAsset",
        "VideoWorkflowVersion",
        "WorkflowEdge",
        "WorkflowNode",
        "WorkspaceAgentRunRequest",
        "WorkspaceCodeGenerationRequest",
        "WorkspaceContentPlanGenerationRequest",
        "WorkspaceRenderJobSubmission",
    }


def test_generated_typescript_uses_no_unbounded_types() -> None:
    typescript = (GENERATED / "contracts.ts").read_text(encoding="utf-8")

    assert ": any" not in typescript
    assert ": unknown" not in typescript
    assert "[key: string]" not in typescript
