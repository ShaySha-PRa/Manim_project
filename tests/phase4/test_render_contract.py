from pathlib import Path

import pytest
from manim_workbench_runner.rendering import (
    FINAL_PROFILE,
    PREVIEW_PROFILE,
    RenderFailureCode,
    RenderProfile,
    RenderRequest,
    build_cache_key,
)


def request_for(source_path: Path, profile: RenderProfile = RenderProfile.PREVIEW) -> RenderRequest:
    return RenderRequest(
        scene_id="quadratic_formula",
        scene_class="QuadraticFormulaDerivation",
        source_path=source_path,
        profile=profile,
        artifact_root=Path("runtime/phase4"),
    )


def test_profiles_are_fixed_to_phase4_contract() -> None:
    assert PREVIEW_PROFILE.quality == "l"
    assert PREVIEW_PROFILE.width == 854
    assert PREVIEW_PROFILE.height == 480
    assert PREVIEW_PROFILE.frame_rate == 15
    assert PREVIEW_PROFILE.timeout_seconds == 60
    assert FINAL_PROFILE.quality == "h"
    assert FINAL_PROFILE.width == 1920
    assert FINAL_PROFILE.height == 1080
    assert FINAL_PROFILE.frame_rate == 60
    assert FINAL_PROFILE.timeout_seconds == 300


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scene_id", ""),
        ("scene_id", "../escape"),
        ("scene_class", "not-a-class"),
        ("source_path", Path("../outside.py")),
        ("source_path", Path("/absolute/scene.py")),
        ("artifact_root", Path("/absolute/artifacts")),
        ("profile", "preview"),
    ],
)
def test_render_request_rejects_unsafe_values(field: str, value: object) -> None:
    values = {
        "scene_id": "quadratic_formula",
        "scene_class": "QuadraticFormulaDerivation",
        "source_path": Path("reference_scenes/formula/quadratic_formula.py"),
        "profile": RenderProfile.PREVIEW,
        "artifact_root": Path("runtime/phase4"),
    }
    values[field] = value
    with pytest.raises(ValueError):
        RenderRequest(**values)


def test_cache_key_is_stable_and_sensitive_to_render_inputs(tmp_path: Path) -> None:
    source = tmp_path / "scene.py"
    source.write_text("class SceneA: pass\n", encoding="utf-8")
    request = request_for(Path("reference_scenes/formula/quadratic_formula.py"))

    first = build_cache_key(request, source_bytes=source.read_bytes())
    second = build_cache_key(request, source_bytes=source.read_bytes())
    final = build_cache_key(
        request_for(request.source_path, RenderProfile.FINAL),
        source_bytes=source.read_bytes(),
    )
    changed = build_cache_key(request, source_bytes=b"class SceneA: pass\n# changed\n")

    assert first == second
    assert len(first) == 64
    assert first != final
    assert first != changed


def test_failure_codes_are_explicit_and_have_no_internal_error_escape_hatch() -> None:
    expected = {
        "invalid_request",
        "source_not_found",
        "docker_unavailable",
        "container_start_failed",
        "render_timeout",
        "manim_render_failed",
        "missing_video",
        "empty_video",
        "ffprobe_failed",
        "zero_frames",
        "invalid_duration",
        "ffmpeg_failed",
        "missing_thumbnail",
        "artifact_io_failed",
    }
    assert {item.value for item in RenderFailureCode} == expected
    assert "internal_error" not in expected
