# Manim Community 0.20.1 benchmark

This directory implements the six scenes required by the Phase 2 cross-engine
contract. It is isolated from the shared contract and scorer.

## Reproduce

From this directory, run:

```sh
sg docker -c "./run_benchmark.sh"
```

The harness invokes `docker` for each render (the outer `sg docker` supplies the
current session's group membership), runs the official `v0.20.1` image pinned
to the accepted immutable digest in headless low quality (`-ql`), disables
caching, and runs each scene twice in independent containers. It records every
command, duration, exit code, log path, output path and SHA-256 in `result.json`
only after a real environment probe and all 12 invocations.

`artifacts/` is deliberately untracked. The accepted Phase 2 evidence summary is
versioned in `../results/manimce-summary.json`. If the initial environment probe fails,
the harness writes `BLOCKED.md` with the raw failing command/output and does not
write `result.json`.

## API sources

- [CoordinateSystem / Axes API, Manim Community v0.20.1](https://docs.manim.community/en/stable/reference/manim.mobject.graphing.coordinate_systems.CoordinateSystem.html)
- [always_redraw API, Manim Community v0.20.1](https://docs.manim.community/en/stable/reference/manim.animation.updaters.mobject_update_utils.html)

The first source documents `Axes.plot`, `get_riemann_rectangles` and coordinate
conversion; the second documents dynamic frame-by-frame regeneration used in
the parameter sweep and moving tangent scenes.
