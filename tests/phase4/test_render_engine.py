from pathlib import Path

from manim_workbench_runner.rendering import (
    CommandResult,
    RenderEngine,
    RenderFailureCode,
    RenderProfile,
    RenderRequest,
)


class MissingDockerRunner:
    def run(self, command: list[str], *, timeout_seconds: int) -> CommandResult:
        raise FileNotFoundError("docker")


class NonzeroRenderRunner:
    def run(self, command: list[str], *, timeout_seconds: int) -> CommandResult:
        return CommandResult(tuple(command), 2, "Manim failed", 0.1)


def request() -> RenderRequest:
    return RenderRequest(
        scene_id="trusted_scene",
        scene_class="TrustedScene",
        source_path=Path("reference_scenes/trusted_scene.py"),
        profile=RenderProfile.PREVIEW,
        artifact_root=Path("runtime/tests"),
    )


def prepare_project(tmp_path: Path) -> None:
    source = tmp_path / "reference_scenes" / "trusted_scene.py"
    source.parent.mkdir()
    source.write_text("class TrustedScene: pass\n", encoding="utf-8")


def test_missing_docker_has_explicit_failure_and_preserved_log(tmp_path: Path) -> None:
    prepare_project(tmp_path)
    result = RenderEngine(project_root=tmp_path, command_runner=MissingDockerRunner()).render(
        request()
    )

    assert result.succeeded is False
    assert result.code is RenderFailureCode.DOCKER_UNAVAILABLE
    assert result.log_relative_path is not None
    assert (tmp_path / result.log_relative_path).is_file()
    assert not list((tmp_path / "runtime" / "tests").glob(".*-*"))


def test_manim_nonzero_is_not_reported_as_internal_error(tmp_path: Path) -> None:
    prepare_project(tmp_path)
    result = RenderEngine(project_root=tmp_path, command_runner=NonzeroRenderRunner()).render(
        request()
    )

    assert result.succeeded is False
    assert result.code is RenderFailureCode.MANIM_RENDER_FAILED
    assert result.exit_code == 2
