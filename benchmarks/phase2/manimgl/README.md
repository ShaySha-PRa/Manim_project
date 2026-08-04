# ManimGL v1.7.2 Phase 2 benchmark

This directory implements the six scenes in `../CONTRACT.md` for the fixed
3b1b ManimGL release `v1.7.2`. The container uses Xvfb and Mesa llvmpipe for
headless software OpenGL. Every scene is invoked independently twice at low
quality. Full logs and videos are written under ignored `artifacts/` paths.

ManimGL has been eliminated by ADR-001. The runner now refuses normal execution
and is retained only to reproduce historical evidence. Production work must not
depend on this directory.

## Run

The current WSL session receives Docker group membership through `sg docker`:

```bash
cd benchmarks/phase2/manimgl
python3 -m unittest tests/test_static_contract.py
bash -n scripts/run_benchmark.sh
sg docker -c "docker info --format '{{.ServerVersion}}'"
sg docker -c "ALLOW_ELIMINATED_MANIMGL_REPRO=1 ./scripts/run_benchmark.sh"
```

`run_benchmark.sh` builds from the Git release tag `v1.7.2`, verifies that the
checkout HEAD has that exact tag, records exact Python, FFmpeg, LaTeX and font
package versions, then records exit code, elapsed wall time, command, log path,
output path and SHA-256 for each invocation. It creates `result.json` only after
all 12 invocations were attempted; failed runs remain explicit and disqualify
the engine through the shared scorer.

The generated capability scores remain zero and explicitly deferred; the
parent agent must visually sample all six scene types and assess capability and
deployment evidence before engine selection.

## Official fixed-version sources

- ManimGL `v1.7.2` README and CLI (`-w` writes without using the `-o` open flag):
  https://github.com/3b1b/manim/blob/v1.7.2/README.md
- Official `v1.7.2` example scenes and animation syntax:
  https://github.com/3b1b/manim/blob/v1.7.2/example_scenes.py
- Official `v1.7.2` coordinate-system implementation used by `Axes`, graphs,
  coordinates and Riemann rectangles:
  https://github.com/3b1b/manim/blob/v1.7.2/manimlib/mobject/coordinate_systems.py
- Official release page:
  https://github.com/3b1b/manim/releases/tag/v1.7.2

## Evidence boundary

No Docker build or render was completed while preparing this implementation.
Therefore this commit contains no `result.json`, successful timing, output hash
or runtime claim. See `BLOCKED.md` for the exact available execution evidence.
