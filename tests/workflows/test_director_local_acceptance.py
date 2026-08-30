from __future__ import annotations

import json

import pytest
from manim_workbench_api.workflows.director import parse_director_candidate


def _case(
    first_pipeline: str,
    second_pipeline: str,
    *,
    first_prompt: str,
    second_prompt: str,
    asset_requirement: str | None = None,
    confirmation_kind: str | None = None,
) -> str:
    confirmations = []
    if confirmation_kind is not None:
        confirmations.append(
            {
                "code": "case_confirmation_required",
                "message": "Confirm the missing or ambiguous evidence.",
                "scene_position": 2,
                "kind": confirmation_kind,
            }
        )
    return json.dumps(
        {
            "global_brief": {
                "title": "Held-out Director case",
                "language": "zh-CN",
                "target_duration_seconds": 60,
                "aspect_ratio": "16:9",
                "style_preset": "dark_scientific",
                "background": "#10131a",
                "palette": ["#4488ff", "#ffcc22"],
                "notation": {},
                "scientific_parameters": {},
            },
            "scenes": [
                {
                    "title": "Scene 1",
                    "prompt": first_prompt,
                    "pipeline_mode": first_pipeline,
                    "target_duration_seconds": 30,
                    "asset_requirements": [],
                    "semantic_summary": "Establish the verified context.",
                },
                {
                    "title": "Scene 2",
                    "prompt": second_prompt,
                    "pipeline_mode": second_pipeline,
                    "target_duration_seconds": 30,
                    "asset_requirements": [asset_requirement] if asset_requirement else [],
                    "semantic_summary": "Complete the requested explanation.",
                },
            ],
            "assumptions": ["Do not invent missing evidence."],
            "confirmations": confirmations,
        },
        ensure_ascii=False,
    )


@pytest.mark.parametrize(
    ("candidate", "pipelines", "confirmation"),
    [
        (
            _case(
                "teaching",
                "teaching",
                first_prompt="Explain completing the square.",
                second_prompt="Verify the derived vertex formula.",
            ),
            ("teaching", "teaching"),
            None,
        ),
        (
            _case(
                "teaching",
                "scientific",
                first_prompt="Explain the Lorenz equations.",
                second_prompt="Compute and show bounded Lorenz trajectories.",
            ),
            ("teaching", "scientific"),
            None,
        ),
        (
            _case(
                "scientific",
                "scientific",
                first_prompt="Show a bounded wave collision.",
                second_prompt="Compare the verified interference field.",
            ),
            ("scientific", "scientific"),
            None,
        ),
        (
            _case(
                "teaching",
                "scientific",
                first_prompt="Explain what an anomaly interval means.",
                second_prompt="Use the uploaded CSV to show real anomalies.",
                asset_requirement="CSV with time and numeric measurements",
                confirmation_kind="asset_required",
            ),
            ("teaching", "scientific"),
            "asset_required",
        ),
        (
            _case(
                "auto",
                "auto",
                first_prompt="Introduce the requested paper without inventing it.",
                second_prompt="Reproduce the paper only after its content is provided.",
                asset_requirement="paper content",
                confirmation_kind="asset_required",
            ),
            ("auto", "auto"),
            "asset_required",
        ),
        (
            _case(
                "teaching",
                "auto",
                first_prompt="Explain the known high-level context.",
                second_prompt="Clarify whether computation or teaching is intended.",
                confirmation_kind="needs_confirmation",
            ),
            ("teaching", "auto"),
            "needs_confirmation",
        ),
        (
            _case(
                "scientific",
                "scientific",
                first_prompt="Describe the uploaded sensor columns without values.",
                second_prompt="Process the data only after the CSV is provided.",
                asset_requirement="sensor CSV",
                confirmation_kind="asset_required",
            ),
            ("scientific", "scientific"),
            "asset_required",
        ),
        (
            _case(
                "teaching",
                "auto",
                first_prompt="Explain only the verified mathematical context.",
                second_prompt="Request the missing formula before animation planning.",
                confirmation_kind="needs_confirmation",
            ),
            ("teaching", "auto"),
            "needs_confirmation",
        ),
    ],
)
def test_eight_local_director_cases_preserve_route_and_evidence_boundaries(
    candidate: str, pipelines: tuple[str, str], confirmation: str | None
) -> None:
    draft = parse_director_candidate(candidate)
    assert tuple(scene.pipeline_mode.value for scene in draft.scenes) == pipelines
    assert sum(scene.target_duration_seconds for scene in draft.scenes) == 60
    kinds = tuple(item.kind for item in draft.confirmations)
    assert (kinds[0] if kinds else None) == confirmation
    assert "source_code" not in candidate and "animation_ir" not in candidate
