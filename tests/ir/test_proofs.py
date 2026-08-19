from manim_workbench_api.code_generation.gallery_fixtures import pythagorean_proof_storyboard
from manim_workbench_api.code_generation.ir_compiler import compile_storyboard
from manim_workbench_api.code_generation.security import validate_source_security
from manim_workbench_api.quality.proofs import score_geometry_proof
from manim_workbench_contracts.ir import GeometryProofRating


def test_proof_ir_compiles_and_can_fail_math_veto() -> None:
    storyboard = pythagorean_proof_storyboard()
    source = compile_storyboard(storyboard).segments[0].source
    assert "prove" in source
    assert validate_source_security(source).allowed
    failed = score_geometry_proof(
        storyboard.steps[0],
        GeometryProofRating(
            given_complete=True,
            prove_matches=True,
            math_correct=2,
            visual_clear=5,
        ),
    )
    assert failed.passed is False
