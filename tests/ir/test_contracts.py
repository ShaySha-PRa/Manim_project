from manim_workbench_contracts import CONTRACT_SCHEMA_VERSION, CodeGenerationMode, VisualKind
from manim_workbench_contracts.ir import GeometryProofRating, SceneStep
from manim_workbench_contracts.ir import VisualKind as IrVisualKind


def test_contract_schema_is_18() -> None:
    assert CONTRACT_SCHEMA_VERSION == "1.10"
    assert CodeGenerationMode.COMPILED_IR.value == "compiled_ir"
    assert VisualKind.THREE_D.value == "three_d"


def test_geometry_proof_rating_veto() -> None:
    rating = GeometryProofRating(
        given_complete=True,
        prove_matches=True,
        math_correct=3,
        visual_clear=5,
    )
    assert rating.passed is False
    passed = GeometryProofRating(
        given_complete=True,
        prove_matches=True,
        math_correct=4,
        visual_clear=4,
    )
    assert passed.passed is True


def test_storyboard_requires_proof_fields() -> None:
    try:
        SceneStep(
            goal="proof",
            duration_seconds=10,
            visual_kind=IrVisualKind.GEOMETRY_PROOF,
        )
    except ValueError as error:
        assert "given" in str(error)
    else:
        raise AssertionError("geometry_proof must require given/prove/steps")
