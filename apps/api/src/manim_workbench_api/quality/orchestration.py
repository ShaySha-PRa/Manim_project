from __future__ import annotations

from manim_workbench_contracts import (
    ContentPlanVersion,
    PipelineStage,
    QualityDiagnostic,
    QualityDiagnosticCode,
    QualitySeverity,
)

from .temporal import (
    ContentPlanExpectation,
    DiagnosticSeverity,
    MediaTiming,
    PlanSceneExpectation,
    TemporalQualityReport,
    analyze_temporal_quality,
)

_SUGGESTIONS = {
    QualityDiagnosticCode.DURATION_TOO_SHORT: (
        "Distribute additional explanatory animations across the planned teaching scenes."
    ),
    QualityDiagnosticCode.DURATION_TOO_LONG: (
        "Shorten redundant animation steps without removing planned teaching content."
    ),
    QualityDiagnosticCode.LONG_STATIC_SEGMENT: (
        "Replace long static holds with meaningful explanation or progressive animation."
    ),
    QualityDiagnosticCode.TERMINAL_WAIT_PADDING: (
        "Remove terminal padding and allocate time to instructional animation steps."
    ),
}


def diagnose_content_plan_timeline(
    *,
    source_code: str,
    content_plan: ContentPlanVersion,
    actual_media: MediaTiming | None = None,
    preview_media: MediaTiming | None = None,
    final_media: MediaTiming | None = None,
) -> tuple[TemporalQualityReport, tuple[QualityDiagnostic, ...]]:
    """Carry the immutable ContentPlan target into static and rendered diagnostics."""
    expectation = ContentPlanExpectation(
        scenes=tuple(
            PlanSceneExpectation(
                scene_number=scene.scene_number,
                required_formula_expressions=tuple(step.expression for step in scene.formula_steps),
            )
            for scene in content_plan.scenes
        )
    )
    temporal = analyze_temporal_quality(
        source_code,
        target_duration_seconds=content_plan.target_duration_seconds,
        actual_media=actual_media,
        preview_media=preview_media,
        final_media=final_media,
        content_plan=expectation,
    )
    diagnostics = tuple(
        QualityDiagnostic(
            code=QualityDiagnosticCode(item.code.value),
            severity=QualitySeverity(item.severity.value),
            stage=PipelineStage.QUALITY_ANALYSIS,
            message=item.message,
            suggestion=_SUGGESTIONS.get(
                QualityDiagnosticCode(item.code.value),
                "Regenerate the affected teaching step using the recorded diagnostic category.",
            ),
            measured_value=item.measured_value,
            threshold_value=item.threshold_value,
        )
        for item in temporal.diagnostics
        if item.severity is not DiagnosticSeverity.INFO
    )
    return temporal, diagnostics
