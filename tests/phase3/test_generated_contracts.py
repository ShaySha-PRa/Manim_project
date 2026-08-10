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
        "ApiErrorDetail",
        "ApiErrorResponse",
        "Artifact",
        "ArtifactDescriptor",
        "AuthenticatedUser",
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
        "Experiment",
        "ExperimentCreateRequest",
        "ExperimentDraft",
        "ExperimentDraftUpdateRequest",
        "ExperimentPage",
        "ExperimentPatchProposal",
        "ExperimentPatchProposalApplyRequest",
        "ExperimentPatchProposalPage",
        "ExperimentPatchProposalRejectRequest",
        "ExperimentVersion",
        "ExperimentVersionCreateRequest",
        "ExperimentVersionPage",
        "GenerationAttempt",
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
        "User",
        "WorkspaceCodeGenerationRequest",
        "WorkspaceContentPlanGenerationRequest",
        "WorkspaceRenderJobSubmission",
    }


def test_generated_typescript_uses_no_unbounded_types() -> None:
    typescript = (GENERATED / "contracts.ts").read_text(encoding="utf-8")

    assert ": any" not in typescript
    assert ": unknown" not in typescript
    assert "[key: string]" not in typescript
