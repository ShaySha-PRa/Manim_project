# ADR-001: Select Manim Community as the rendering engine

## Status

Accepted

## Date

2026-08-04

## Context

The first release needs reliable headless rendering for formula derivations and function visualizations on Windows, WSL2 and Docker Desktop. Phase 2 compared six equivalent teaching scenes: formula transformation, derivative derivation, function plotting, parameter animation, tangent animation and area visualization.

The predeclared rule disqualifies an engine that cannot complete all 12 runs. If both qualify within 10 weighted points, Manim Community wins the tie.

## Decision

Use Manim Community `0.20.1` through the immutable official image digest:

```text
manimcommunity/manim@sha256:f18f53f2e4eaf2ea41713437d34363fb3f5cc6008b03fd798676ac0359396c3b
```

Lock Python `3.14.3`, PyAV `16.1.0` with libavcodec `62.11.100` and libavformat `62.3.100`, pdfTeX `1.40.28` from TeX Live 2025, and Noto Sans/Serif/Mono Regular as the Phase 3 baseline.

## Evidence

ManimCE completed 12 of 12 clean low-quality headless renders. All six scenes succeeded on their first attempt. Mean wall time was 7.543 seconds, with a range of 5.083–10.292 seconds. Parent review sampled the final frame of all six scene types; core mathematical objects were clear, with minor label overlap in two scenes.

ManimGL's fixed `v1.7.2` image built, but both attempts at the first formula scene stalled in `xvfb-run` before a `manimgl` process appeared. Both ended with exit code 130 and produced no video. The project owner explicitly stopped further retries, so ManimGL did not satisfy the 12-run gate and was disqualified.

## Alternatives Considered

### ManimGL v1.7.2

- Strength: rich interactive OpenGL workflow and direct lineage from 3Blue1Brown.
- Cost: custom 694 MB image, Xvfb/Mesa setup, undocumented package/tag mismatch (`v1.7.2` checkout reports package `1.7.1`), and failed headless startup in this environment.
- Rejected: it failed the mandatory headless stability gate.

## Consequences

- Phase 3 contracts and Phase 4 reference scenes will target Manim Community only.
- Generated code must import `manim`, not `manimlib`.
- Rendering remains containerized and pinned by digest; moving `stable` and `latest` tags are forbidden.
- Native CE sections and caching may be used after correctness baselines, but benchmark timing keeps caching disabled.
- ManimGL benchmark code remains as historical evidence, not a supported runtime.

## Official Sources

- https://docs.manim.community/en/stable/installation/docker.html
- https://docs.manim.community/en/stable/changelog.html
- https://docs.manim.community/en/stable/guides/configuration.html
- https://github.com/3b1b/manim/tree/v1.7.2
