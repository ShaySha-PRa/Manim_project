"""Canonical, content-free Redis wake-up signals for persistent workflow tasks."""

from __future__ import annotations

from uuid import UUID

WORKFLOW_SIGNAL_KEYS = {
    "scene_program": "manim-workbench:workflows:scene-program",
    "composition": "manim-workbench:workflows:composition",
    "director_plan": "manim-workbench:workflows:director-plan",
}


def encode_workflow_signal(task_id: UUID) -> bytes:
    if not isinstance(task_id, UUID):
        raise TypeError("workflow task_id must be a UUID")
    return str(task_id).encode("ascii")


def decode_workflow_signal(payload: bytes) -> UUID:
    if type(payload) is not bytes:
        raise TypeError("workflow signal must be bytes")
    try:
        encoded = payload.decode("ascii")
        task_id = UUID(encoded)
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("workflow signal must be a canonical UUID") from error
    if encoded != str(task_id):
        raise ValueError("workflow signal must be a canonical UUID")
    return task_id
