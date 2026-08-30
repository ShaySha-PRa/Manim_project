# Composable Scene Workflow MVP Evidence

## Scope and candidate identity

This evidence covers OpenSpec change `add-composable-scene-workflow-mvp`. The candidate is the
checked-out `feature/composable-scene-workflow-mvp` commit reported by `git rev-parse HEAD` when
the final commands below are run. The MVP is deliberately linear: 2–8 independently versioned
scene blocks followed by Compose and Export. Free-form DAGs, transitions, audio, subtitles,
Director automation and the cancelled external-user phase are not included.

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
| Full Python suite | `uv run pytest -vv --durations=50 -o faulthandler_timeout=60` | 734 collected and 734 passed; no artificial skip or manual interruption |
| Web gates | `npm --prefix apps/web run lint`, `typecheck`, and `build` | all passed; production build generated all routes offline |

The Docker black-box case uses a deterministic bounded teaching-plan fixture so it can be
repeated offline. The scientific scenes use the production catalog resolver, allowlisted Lorenz
and CSV tools, actual generated NPZ data, deterministic AnimationIR compiler, production asset
mounting, and the pinned Manim Docker image. It verifies a common GlobalBrief hash, Preview
profile, CSV column provenance, Lorenz 3D scene selection, ordered clip identities, frame-level
duration tolerance, decodability, and no remaining `manim-wb-*` containers.

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
