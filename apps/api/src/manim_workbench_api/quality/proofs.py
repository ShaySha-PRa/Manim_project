"""Human scoring for geometry-proof IR."""

from manim_workbench_contracts.ir import GeometryProofRating, SceneStep, VisualKind


def score_geometry_proof(step: SceneStep, rating: GeometryProofRating) -> GeometryProofRating:
    if step.visual_kind is not VisualKind.GEOMETRY_PROOF:
        raise ValueError("score_geometry_proof requires a geometry_proof step")
    structural_ok = bool(step.given) and step.prove is not None and bool(step.proof_steps)
    if not structural_ok:
        return rating.model_copy(update={"given_complete": False, "prove_matches": False})
    return rating
