# Composable Scene Workflow MVP Evidence

## Scope and candidate identity

This evidence covers OpenSpec change `add-composable-scene-workflow-mvp`. The candidate is the
checked-out `feature/composable-scene-workflow-mvp` commit reported by `git rev-parse HEAD` when
the final commands below are run. The MVP is deliberately linear: 2–8 independently versioned
scene blocks followed by Compose and Export. Free-form DAGs, transitions, audio, subtitles,
Director automation, and Phase 10 are not included.

## Implemented behavior

- Teaching and scientific adapters retain their separate constrained planning/IR semantics and
  both return the shared `CompiledProgram` type.
- Every program segment is persisted as a typed render source, submitted as an independent
  RenderJob, and either reused directly or hard-cut into one scene clip.
- Workflow, block, program-render, scene-run, composition-run, event, and artifact records are
  immutable or append-only and owner/project scoped.
- Scene and composition keys include the semantic inputs needed for safe reuse. A changed block
  invalidates only that block; a reordered workflow retains scene clips and invalidates only the
  composition.
- The API is asynchronous and backed by durable SQLite tasks plus lossy Redis wakeups. Expired
  leases and lost signals are recoverable without duplicate terminal events or partial artifacts.
- The production Web workbench supports global settings, 2–8 scene cards, versioned editing,
  accessible reordering, individual generation/preview, full composition, refresh recovery,
  provenance, failure states, and authenticated download.

## Acceptance evidence

All commands are rerun after the evidence file is committed so the reported final result belongs
to one candidate SHA.

| Gate | Command | Expected/recorded result |
| --- | --- | --- |
| Workflow suite | `uv run pytest tests/workflows tests/web/workflow/test_workflow_editor.py -vv --durations=30 -o faulthandler_timeout=60` | 106 passed before the final candidate rerun; no leftover workflow Docker containers or test processes |
| Real workflow Docker black box | `uv run pytest tests/workflows/test_workflow_docker_acceptance.py -vv -o faulthandler_timeout=300 --durations=10` | 1 passed in 65.96s: teaching + Lorenz 3D + CSV anomaly, all generated segments rendered, ordered manifest and final MP4 decoded |
| Local rerun, stop, failure, recovery | focused cache/composition/executor/API-runner/recovery command recorded in the final report | 41 passed in 3.37s |
| Protected migrations | focused protected migration matrix recorded in the final report | 20 passed before the final candidate rerun |
| Browser workflow | `npm --prefix apps/web exec playwright test -- --config tests/web/workflow/workflow.playwright.config.ts` with local Chromium and media-fixture paths | 1 passed in 19.1s before the final candidate rerun: create, refresh, edit-one, reorder-only, same-origin Cookie/CSRF, and cross-owner 404 |
| Python static checks | `uv run ruff check . --no-cache` and `git diff --check` | rerun on the final candidate |
| Contract drift | `uv run python scripts/generate_contracts.py --check` | rerun on the final candidate; schema 1.11 |
| Locked dependencies | `uv lock --check` | rerun on the final candidate |
| Full Python suite | `uv run pytest -vv --durations=50 -o faulthandler_timeout=60` | rerun on the final candidate; count is taken from collection rather than hard-coded |
| Web gates | `npm --prefix apps/web run lint`, `typecheck`, and `build` | rerun on the final candidate production build |

The Docker black-box case uses a deterministic bounded teaching-plan fixture so it can be
repeated offline. The scientific scenes use the production catalog resolver, allowlisted Lorenz
and CSV tools, actual generated NPZ data, deterministic AnimationIR compiler, production asset
mounting, and the pinned Manim Docker image. It verifies a common GlobalBrief hash, Preview
profile, CSV column provenance, Lorenz 3D scene selection, ordered clip identities, frame-level
duration tolerance, decodability, and no remaining `manim-wb-*` containers.

## Migration evidence

The schema contract is 1.11 and the migration head is `0010_video_workflows.py`. Revision 0009 is
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

No tag, push, deployment, external-user phase, or Phase 10 action is part of this change.
