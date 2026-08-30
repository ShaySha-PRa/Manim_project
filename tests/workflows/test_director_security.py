from __future__ import annotations

import json

import pytest
from manim_workbench_api.workflows.director import (
    DirectorCandidateError,
    parse_director_candidate,
)


def _valid_payload() -> dict[str, object]:
    return {
        "global_brief": {
            "title": "A bounded scientific story",
            "language": "zh-CN",
            "target_duration_seconds": 60,
            "aspect_ratio": "16:9",
            "style_preset": "dark_scientific",
            "background": "#10131a",
            "palette": ["#4c8dff", "#ffd84c"],
            "notation": {},
            "scientific_parameters": {},
        },
        "scenes": [
            {
                "title": "Concept",
                "prompt": "Explain the verified concept.",
                "pipeline_mode": "teaching",
                "target_duration_seconds": 30,
                "asset_requirements": [],
                "semantic_summary": "Introduce the concept.",
            },
            {
                "title": "Evidence",
                "prompt": "Visualize the verified bounded computation.",
                "pipeline_mode": "scientific",
                "target_duration_seconds": 30,
                "asset_requirements": [],
                "semantic_summary": "Show computed evidence.",
            },
        ],
        "assumptions": ["Use only verified inputs."],
        "confirmations": [],
    }


@pytest.mark.parametrize(
    "candidate",
    [
        "```json\n{}\n```",
        json.dumps({**_valid_payload(), "animation_ir": {}}),
        json.dumps({**_valid_payload(), "tool_calls": ["lorenz_ensemble"]}),
        json.dumps({**_valid_payload(), "source_code": "from manim import Scene"}),
        json.dumps({**_valid_payload(), "escape": True}),
        json.dumps(
            {
                **_valid_payload(),
                "scenes": [
                    {
                        **_valid_payload()["scenes"][0],  # type: ignore[index]
                        "prompt": "lambda x: x",
                    },
                    _valid_payload()["scenes"][1],  # type: ignore[index]
                ],
            }
        ),
    ],
)
def test_director_rejects_code_ir_tool_and_unknown_candidates(candidate: str) -> None:
    with pytest.raises(DirectorCandidateError):
        parse_director_candidate(candidate)


def test_director_rejects_duplicate_json_keys() -> None:
    candidate = json.dumps(_valid_payload())
    duplicate = candidate.replace(
        '"assumptions":', '"assumptions":[],"assumptions":', 1
    )
    with pytest.raises(DirectorCandidateError, match="duplicate"):
        parse_director_candidate(duplicate)


def test_director_rejects_oversized_candidate() -> None:
    candidate = json.dumps(
        {**_valid_payload(), "assumptions": ["x" * 70_000]}
    )
    with pytest.raises(DirectorCandidateError, match="large"):
        parse_director_candidate(candidate)


def test_director_accepts_only_the_strict_draft_shape() -> None:
    draft = parse_director_candidate(json.dumps(_valid_payload()))
    assert len(draft.scenes) == 2
    assert draft.global_brief.target_duration_seconds == 60
