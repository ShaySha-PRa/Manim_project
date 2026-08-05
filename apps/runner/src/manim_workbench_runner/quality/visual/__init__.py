"""Deterministic, bounded visual diagnostics for rendered media."""

from .analysis import VisualDiagnosticAnalyzer, deterministic_frame_indices
from .models import (
    ExpectedObjectProxy,
    FrameSample,
    MediaAnalysisError,
    MediaMetadata,
    VisualAnalysisResult,
    VisualDiagnostic,
    VisualLimits,
    validate_relative_media_path,
)
from .reader import PyAVVideoReader, VideoReader

__all__ = [
    "ExpectedObjectProxy",
    "FrameSample",
    "MediaAnalysisError",
    "MediaMetadata",
    "PyAVVideoReader",
    "VideoReader",
    "VisualAnalysisResult",
    "VisualDiagnostic",
    "VisualDiagnosticAnalyzer",
    "VisualLimits",
    "deterministic_frame_indices",
    "validate_relative_media_path",
]
