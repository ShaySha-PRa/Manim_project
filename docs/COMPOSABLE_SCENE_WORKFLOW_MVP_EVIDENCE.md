# Composable Scene Workflow MVP Evidence

## Scope and candidate identity

This evidence covers the implemented and merged OpenSpec change
`add-composable-scene-workflow-mvp`. The current candidate is the checked-out `main` tree reported
by `git rev-parse HEAD`; the exact local commit and remote divergence are reported at handoff. The
MVP is deliberately linear: 2–8 independently versioned scene blocks followed by Compose and
Export. Free-form DAGs, transitions, audio, subtitles, Director automation and the cancelled
external-user phase are not included.

## Implemented behavior

- Teaching and scientific adapters retain their separate constrained planning/IR semantics and
  both return the shared `CompiledProgram` type.
- Every program segment is persisted and submitted as an independent RenderJob: teaching
  segments retain real CodeVersion identity, while scientific segments use typed
  ProgramRenderSegment identity. One segment is reused directly and multiple segments are
  hard-cut into one scene clip.
- Workflow, block, program-render, scene-run, composition-run, event, and artifact records are
  immutable or append-only and owner/project scoped.
- Scene and composition keys include the semantic inputs needed for safe reuse. A changed block
  invalidates only that block; a reordered workflow retains scene clips and invalidates only the
  composition. Cache hits revalidate owner/project/profile, size, SHA-256, path and decodability,
  then publish a new immutable run-scoped artifact without calling the Provider, tools or Docker.
- CSV content enters through the authenticated project API, is persisted behind an immutable
  owner/project-scoped `WorkflowAssetVersion`, verified against its hash and size, and is loaded
  by the Runner rather than copied into the queue payload. Identical content is idempotent within
  a project but receives a distinct identity across projects or owners. Scientific runs persist
  IntentSpec, tool, AnimationIR and compiler provenance; an authenticated endpoint and the Web
  workbench expose the complete evidence, cache-hit runs receive their own immutable evidence
  record, and composition manifests retain its references.
- The API is asynchronous and backed by durable SQLite tasks plus lossy Redis wakeups. Expired
  leases and lost signals are recoverable without duplicate terminal events or partial artifacts.
- The production Web workbench supports global settings, 2–8 scene cards, versioned editing,
  accessible reordering, complete notation/scientific-parameter settings, individual
  generation/preview, full composition, refresh recovery,
  provenance, failure states, and authenticated download. Preview and Final runs are tracked by
  separate profile-qualified identities, so one cannot satisfy the other profile's compose gate.
- Next.js production builds explicitly use its TypeScript compiler API. Next 16.3's experimental
  CLI capture returned exit code 0 with empty `--showConfig` stdout under the current Node/WSL
  environment, so JSON parsing failed after compilation; the compiler API keeps Next's type check
  active and is backed by the separate `tsc --noEmit` gate.

## Acceptance evidence

All commands are rerun after the evidence file is committed so the reported final result belongs
to one candidate SHA.

| Gate | Command | Expected/recorded result |
| --- | --- | --- |
| Workflow suite | `uv run pytest -q tests/workflows tests/web/workflow -o faulthandler_timeout=60` | 109 passed; includes real Docker cases |
| Real workflow Docker black box | full-suite case `tests/workflows/test_workflow_docker_acceptance.py` | passed: teaching + Lorenz 3D + CSV anomaly, all generated segments rendered, ordered manifest and final MP4 decoded |
| Scene cache, bound CSV and provenance | focused workflow executor tests plus the full suite | same-key retry reused the verified clip with no new RenderJob; bound CSV reached the scientific adapter and Intent/IR provenance refs remained visible |
| API/auth/Workflow HTTP | `uv run pytest -q tests/workflows/test_api.py tests/workflows/test_api_runner_integration.py tests/phase8 tests/phase9` | 157 passed |
| Protected migrations | `uv run pytest -q tests/workflows/test_migration.py tests/workflows/test_protected_render_job_migration.py tests/workflows/test_render_job_shadow_migration.py tests/workflows/test_typed_render_jobs.py` | 19 passed |
| Browser workflow | `PHASE8_BROWSER_EVIDENCE_ROOT=<local-runtime> MANIM_PLAYWRIGHT_CHROMIUM=<locked-chromium> npm --prefix apps/web exec playwright test -- --config tests/web/workflow/workflow.playwright.config.ts` | 1 passed: create, refresh, edit-one, reorder-only, same-origin Cookie/CSRF, and cross-owner 404 |
| Python static checks | `uv run ruff check .` and `git diff --check` | passed |
| Contract drift | `uv run python scripts/generate_contracts.py --check` | passed; schema 1.12 |
| Locked dependencies | `uv lock --check` | passed |
| Full Python suite | `uv run pytest -q` after the build and standalone-server regressions were added | 738 collected; run 1 `738 passed in 167.85s`, run 2 `738 passed in 167.27s`; both included real Docker and exited normally |
| Web gates | `npm --prefix apps/web run lint`, `typecheck`, and `build` | all exited 0; production build completed Next TypeScript checking, generated 7/7 routes including `/workflows`, and staged static assets in the standalone output |
| Production browser workflow | Playwright with the built `.next/standalone/apps/web/server.js` | 1 passed in 19.4s; create, refresh, edit-one, reorder-only, same-origin Cookie/CSRF, download, and cross-owner 404 |

The Docker black-box case uses a deterministic bounded teaching-plan fixture so it can be
repeated offline. The scientific scenes use the production catalog resolver, allowlisted Lorenz
and CSV tools, actual generated NPZ data, deterministic AnimationIR compiler, production asset
mounting, and the pinned Manim Docker image. It verifies a common GlobalBrief hash, Preview
profile, CSV column provenance, Lorenz 3D scene selection, ordered clip identities, frame-level
duration tolerance, decodability, and no remaining `manim-wb-*` containers.

The current full-suite repeatability refresh also ran the real P0 Docker preview, real ordered
2D→3D→2D segment render/composition, and real teaching + Lorenz 3D + CSV workflow composition in
both runs. Post-run checks found no `manim-wb-*` container or API/Runner/pytest process left behind.

## Migration evidence

The schema contract is 1.12 and the migration head is `0010_video_workflows.py`. Revision 0009 is
an intentionally protected RenderJob parent-table rebuild. Plain Alembic rejects an unprepared
0008 database. The maintenance command requires stopped writers and a fresh backup, rebuilds via
a shadow table, verifies copied data/foreign keys/integrity, restores on failure, marks 0009, and
then allows ordinary upgrade to 0010. The matrix covers empty and populated databases, existing
Artifact/JobEvent/QualityReport data, marker failure recovery, intermediate restart, a full
no-scientific-job downgrade/upgrade round trip, and downgrade refusal after scientific typed jobs
exist.

## Known limits and residual risk

- This is the scoped MVP, not a free-form node editor or arbitrary DAG executor.
- Scene videos are independent clips; Manim Mobject identity does not cross scene boundaries.
- Composition is video-only hard cut. Audio, narration, subtitles, overlays, split screen, and
  transitions remain out of scope.
- The repeatable Docker acceptance does not spend an external model request. Provider transport
  and strict JSON boundaries remain covered by the existing API/agent suites; production quality
  still depends on the configured provider for prompts outside the deterministic catalog.
- Migrating a deployed 0008 database requires a maintenance window and verified backup; it is
  intentionally not an online Alembic operation.

No tag, push, deployment, or external-user action is part of this change. The previously named
Phase 10 has been cancelled and is not a future project phase.
