"""IR-level repair. At most one pass. Never emits Scene Python."""

from __future__ import annotations

from manim_workbench_contracts import CriticFinding
from manim_workbench_contracts.animation_ir import (
    AnimationIR,
    AnimCameraOp,
    AnimObject,
    CameraOpKind,
    ObjectType,
    TimelineOp,
    TimelineOpKind,
)

MAX_IR_REPAIRS = 1


def repair_animation_ir(ir: AnimationIR, findings: tuple[CriticFinding, ...]) -> AnimationIR:
    objects = list(ir.objects)
    timeline = list(ir.timeline)
    camera = list(ir.camera)
    object_ids = {item.id for item in objects}
    for finding in findings:
        if not finding.repairable:
            continue
        if finding.code == "missing_title" and "title" not in object_ids:
            objects.insert(
                0,
                AnimObject(id="title", type=ObjectType.TITLE, text=ir.goal[:80], color="YELLOW"),
            )
            object_ids.add("title")
            if timeline and timeline[0].op is TimelineOpKind.CREATE:
                targets = timeline[0].targets or ()
                if "title" not in targets:
                    timeline[0] = timeline[0].model_copy(update={"targets": ("title", *targets)})
        elif finding.code == "missing_zoom" and CameraOpKind.ZOOM not in {
            item.op for item in camera
        }:
            camera.append(AnimCameraOp(op=CameraOpKind.ZOOM, run_time=2.0))
        elif finding.code == "missing_3d_camera" and not any(
            item.op is CameraOpKind.SET_ORIENTATION for item in camera
        ):
            camera.append(
                AnimCameraOp(op=CameraOpKind.SET_ORIENTATION, phi_degrees=70, theta_degrees=45)
            )
        elif finding.code == "missing_highlight" and not any(
            item.op is TimelineOpKind.HIGHLIGHT for item in timeline
        ):
            target = next((item.id for item in objects if item.type is ObjectType.REGION), None)
            if target is not None:
                timeline.append(
                    TimelineOp(op=TimelineOpKind.HIGHLIGHT, target=target, duration=2.0)
                )
        elif finding.code == "missing_compare" and not any(
            item.op is TimelineOpKind.COMPARE for item in timeline
        ):
            target = ir.data[0].id if ir.data else None
            timeline.append(TimelineOp(op=TimelineOpKind.COMPARE, target=target, duration=4.0))
    return ir.model_copy(
        update={
            "objects": tuple(objects),
            "timeline": tuple(timeline),
            "camera": tuple(camera),
        }
    )
