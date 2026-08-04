# Phase 2 Cross-Engine Benchmark Contract

## Fixed Candidates

- `manimce`: Manim Community `0.20.1`
- `manimgl`: 3b1b ManimGL release `v1.7.2`

Every environment report must also capture the exact Python, FFmpeg, LaTeX and font versions actually used.

## Scene Contract

| ID | Required observable behavior |
|---|---|
| `formula_transform` | Transform `x²+6x+5=0` through completing-square steps to both roots |
| `derivative` | Derive `d(x²)/dx=2x` from a difference quotient with `h→0` |
| `function_plot` | Draw `y=x²`, axes, vertex and symmetry axis |
| `parameter_sweep` | Animate `a` in `y=a(x-h)²+k` while keeping the vertex visible |
| `tangent` | Move `a` on `y=x³` and update the tangent with slope `3a²` |
| `area` | Show Riemann rectangles converging to the area under `y=x²` on `[0,2]`, ending at `8/3` |

Each scene must be rendered twice from a clean command invocation at low quality, without opening a preview window. The source may use engine-specific APIs, but may not weaken the required observable behavior.

## Result Contract

Each engine writes `result.json` with:

- `engine`: `manimce` or `manimgl`
- `engine_version`, `python_version`, `ffmpeg_version`, `latex_version`, `font_versions`
- `container_or_environment`: immutable image digest or reproducible environment description
- `first_attempt_success`: one boolean per scene ID
- `runs`: exactly 12 entries containing `scene_id`, `iteration`, `success`, `exit_code`, `duration_seconds`, `command`, `output_path`, `output_sha256`, and `log_path`
- `capabilities`: 0–100 `visual_score`, `sections_cache_score`, and `deployment_score`, each with non-empty evidence
- `notes`: setup problems, retries and known limitations

Output videos and full logs go under an ignored `artifacts/` directory. Failed runs still require a log path and exit code; output path and hash may be empty.

## Scoring and Selection

- Headless stability: 40%
- Low-quality render speed: 20%
- First-attempt scene success: 15%
- Formula/function visual capability: 10%
- Sections and caching: 10%
- Image/deployment complexity: 5%

An engine with fewer than 12 successful runs is disqualified. Among qualified engines, the fastest mean time receives 100 speed points and the other receives `fastest_mean / own_mean × 100`. If both qualify and total scores differ by at most 10 points, select ManimCE; otherwise select the higher score. If both are disqualified, Phase 2 remains blocked and no engine is selected.

## Evidence Rules

- Never manufacture timings, hashes, screenshots or success states.
- Record the first attempt before making compatibility fixes.
- Parent review verifies result shape, reruns the scorer and visually samples all six output types.
- A runnable implementation without actual render evidence is “implemented, not benchmarked,” not a pass.
