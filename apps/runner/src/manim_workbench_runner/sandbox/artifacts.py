from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from manim_workbench_contracts.models import ArtifactKind, RenderArtifactPayload

_ARTIFACTS: tuple[tuple[str, ArtifactKind], ...] = (
    ("video.mp4", ArtifactKind.VIDEO),
    ("thumbnail.jpg", ArtifactKind.THUMBNAIL),
    ("render.log", ArtifactKind.RENDER_LOG),
    ("metadata.json", ArtifactKind.METADATA),
)
_ARTIFACT_NAMES = frozenset(name for name, _ in _ARTIFACTS)


class ArtifactValidationError(ValueError):
    """The untrusted output cannot be published as a RenderJob artifact set."""


def _resolved_existing_directory(path: Path, *, field_name: str) -> Path:
    if path.is_symlink():
        raise ArtifactValidationError(f"{field_name} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ArtifactValidationError(f"{field_name} does not exist") from exc
    if not resolved.is_dir():
        raise ArtifactValidationError(f"{field_name} must be a directory")
    return resolved


def _validate_under_root(path: Path, root: Path, *, field_name: str) -> None:
    resolved_root = _resolved_existing_directory(root, field_name="allowed_publish_root")
    if not path.is_relative_to(resolved_root):
        raise ArtifactValidationError(f"{field_name} must stay under its allowed publish root")


def _hash_regular_nonempty_file(path: Path) -> tuple[int, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ArtifactValidationError(f"artifact {path.name} cannot be opened safely") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ArtifactValidationError(f"artifact {path.name} must be a regular file")
        if metadata.st_size <= 0:
            raise ArtifactValidationError(f"artifact {path.name} must not be empty")
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return metadata.st_size, digest.hexdigest()
    finally:
        os.close(descriptor)


def validate_output_directory(
    output_directory: Path,
    *,
    max_total_bytes: int,
) -> tuple[RenderArtifactPayload, ...]:
    """Validate the complete untrusted output set before it reaches persistent storage."""
    if max_total_bytes < 1:
        raise ValueError("max_total_bytes must be positive")
    root = _resolved_existing_directory(output_directory, field_name="output_directory")
    entries = tuple(root.iterdir())
    names = {entry.name for entry in entries}
    unexpected = names - _ARTIFACT_NAMES
    missing = _ARTIFACT_NAMES - names
    if unexpected:
        raise ArtifactValidationError("output contains a non-allowlisted entry")
    if missing:
        raise ArtifactValidationError("output is missing required artifacts")

    total_bytes = 0
    artifacts: list[RenderArtifactPayload] = []
    for name, kind in _ARTIFACTS:
        path = root / name
        if path.is_symlink():
            raise ArtifactValidationError(f"artifact {name} must not be a symlink")
        byte_size, sha256 = _hash_regular_nonempty_file(path)
        total_bytes += byte_size
        if total_bytes > max_total_bytes:
            raise ArtifactValidationError("output exceeds the total size limit")
        artifacts.append(
            RenderArtifactPayload(
                kind=kind,
                relative_path=name,
                sha256=sha256,
                byte_size=byte_size,
            )
        )
    return tuple(artifacts)


def publish_output(
    staging_directory: Path,
    destination_directory: Path,
    *,
    allowed_publish_root: Path,
    max_total_bytes: int = 512 * 1024 * 1024,
) -> tuple[RenderArtifactPayload, ...]:
    """Validate then atomically publish a complete artifact directory without replacement."""
    staging = _resolved_existing_directory(staging_directory, field_name="staging_directory")
    publish_root = _resolved_existing_directory(
        allowed_publish_root,
        field_name="allowed_publish_root",
    )
    _validate_under_root(staging, publish_root, field_name="staging_directory")
    destination = destination_directory.resolve(strict=False)
    _validate_under_root(
        destination.parent.resolve(strict=True),
        publish_root,
        field_name="destination",
    )
    if destination.exists() or destination.is_symlink():
        raise ArtifactValidationError("destination already exists")

    artifacts = validate_output_directory(staging, max_total_bytes=max_total_bytes)
    try:
        os.replace(staging, destination)
    except OSError as exc:
        raise ArtifactValidationError("artifact publish failed") from exc
    return artifacts
