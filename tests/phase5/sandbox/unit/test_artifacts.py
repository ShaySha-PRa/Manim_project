from pathlib import Path

import pytest


def _write_expected_artifacts(directory: Path) -> None:
    for name in ("video.mp4", "thumbnail.jpg", "render.log", "metadata.json"):
        (directory / name).write_bytes(name.encode("ascii"))


def test_validate_output_accepts_exact_nonempty_allowlist_and_hashes_files(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.artifacts import validate_output_directory

    _write_expected_artifacts(tmp_path)
    artifacts = validate_output_directory(tmp_path, max_total_bytes=1_024)

    assert [artifact.relative_path for artifact in artifacts] == [
        "video.mp4",
        "thumbnail.jpg",
        "render.log",
        "metadata.json",
    ]
    assert all(len(artifact.sha256) == 64 for artifact in artifacts)
    assert all(artifact.byte_size > 0 for artifact in artifacts)


@pytest.mark.parametrize("attack", ("symlink", "extra", "empty", "oversize"))
def test_validate_output_rejects_untrusted_artifact_shapes(tmp_path: Path, attack: str) -> None:
    from manim_workbench_runner.sandbox.artifacts import (
        ArtifactValidationError,
        validate_output_directory,
    )

    _write_expected_artifacts(tmp_path)
    if attack == "symlink":
        (tmp_path / "render.log").unlink()
        (tmp_path / "render.log").symlink_to("metadata.json")
    elif attack == "extra":
        (tmp_path / "escape.txt").write_text("no", encoding="utf-8")
    elif attack == "empty":
        (tmp_path / "video.mp4").write_bytes(b"")

    with pytest.raises(ArtifactValidationError):
        validate_output_directory(tmp_path, max_total_bytes=1 if attack == "oversize" else 1_024)


def test_publish_output_validates_then_atomically_moves_within_allowed_root(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.artifacts import publish_output

    staging = tmp_path / "artifacts" / ".staging"
    destination = tmp_path / "artifacts" / "published"
    staging.mkdir(parents=True)
    _write_expected_artifacts(staging)

    artifacts = publish_output(
        staging,
        destination,
        allowed_publish_root=tmp_path / "artifacts",
        max_total_bytes=1_024,
    )

    assert not staging.exists()
    assert {path.name for path in destination.iterdir()} == {
        "video.mp4",
        "thumbnail.jpg",
        "render.log",
        "metadata.json",
    }
    assert len(artifacts) == 4


def test_publish_output_rejects_destination_escape_and_existing_destination(tmp_path: Path) -> None:
    from manim_workbench_runner.sandbox.artifacts import ArtifactValidationError, publish_output

    staging = tmp_path / "root" / ".staging"
    staging.mkdir(parents=True)
    _write_expected_artifacts(staging)
    root = tmp_path / "root"

    with pytest.raises(ArtifactValidationError, match="allowed"):
        publish_output(staging, tmp_path / "outside", allowed_publish_root=root)

    destination = root / "published"
    destination.mkdir()
    with pytest.raises(ArtifactValidationError, match="exists"):
        publish_output(staging, destination, allowed_publish_root=root)
