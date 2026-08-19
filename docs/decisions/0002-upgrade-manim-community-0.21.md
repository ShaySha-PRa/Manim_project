# ADR-002: Upgrade Manim Community to 0.21.0

## Status

Accepted

## Date

2026-08-19

## Context

ADR-001 pinned Manim Community `0.20.1` after the Phase 2 headless gate. ManimCE `0.21.0` was released on 2026-08-10. The workbench is moving from LLM-authored Python to a state-driven Scene IR compiler, so the runtime must track a current CE release without floating `latest` or `stable` tags.

Python `>=3.11` is required inside the official rendering image. The host API remains Python 3.10.

## Decision

Use Manim Community `0.21.0` through the immutable official image digest:

```text
manimcommunity/manim@sha256:89ab433ce59134a4dcf351deb2511e067ab354393c0bb7d1859f3e8f0b2406a3
```

Typst text objects from 0.21.0 are not enabled. Chinese copy continues to use `Text(font="Noto Sans CJK SC")`.

Generated scenes may inherit `Scene`, `MovingCameraScene`, or `ThreeDScene`. The compiler, not the model, chooses the base class.

## Consequences

- Contract `engine_version` and the `code_versions` check constraint become `0.21.0`.
- Phase 2 benchmark harness and Runner sandbox image pins move to this digest.
- ADR-001 remains historical evidence for the original engine selection.
- Cache keys include the new engine version, so previous 0.20.1 artifacts are not reused.
- On 2026-08-19 the six Phase 2 scenes were re-run 2 times each against this digest; all 12 headless invocations succeeded. Evidence: `benchmarks/phase2/results/manimce-0.21.0-summary.json`.
