# Milestone 1: Experiment Foundation

## Purpose

Milestone 1 adds the compatibility foundation for interactive scientific experiments while
leaving the Phase 9 teaching-video workflow unchanged. It introduces experiment contracts,
persistence, authenticated APIs, and feature-flagged Lab and Studio placeholders. It does not
execute scientific models, open WebSockets, call DeepSeek for experiment patches, or render
interactive scenes.

## Global constraints

- Contract schema version is `1.6`; existing ContentPlan, CodeVersion, RenderJob, quality, auth,
  project, workspace, and delivery field semantics remain unchanged.
- Existing `/workbench` behavior, query parameters, authentication, first-password-change flow,
  API routes, user/project data, and rendered-video access remain compatible.
- New `/lab` and `/studio` navigation is disabled by default and controlled independently by
  `NEXT_PUBLIC_EXPERIMENT_LAB_ENABLED` and `NEXT_PUBLIC_STUDIO_ENABLED`.
- Experiments belong to an existing project and its owner. Reads and writes always scope by both
  resource ID and authenticated owner ID.
- A project has many experiments. An experiment has one mutable draft and immutable version
  snapshots. Draft updates use an integer revision and compare-and-swap semantics.
- Patch proposals are stored review objects. Milestone 1 can list, apply, and reject stored
  proposals but does not generate them with an LLM.
- No migration before `0007` may be modified. Upgrade preserves all existing records; downgrade
  removes only Milestone 1 tables and triggers.
- No new runtime dependency is required for Milestone 1.

## Frozen domain boundaries

`ModelSpec` is a stable envelope with a domain discriminator and opaque, JSON-compatible domain
payload. The shared layer validates envelope size and shape but does not encode heat-transfer,
geometry, FEM, neural-network, or renderer-specific fields. Domain plugins introduced in later
milestones will own those payload schemas.

The public contract includes:

- `ExperimentDomainKind`, initially covering generic, geometry, ODE, PDE, FEM, stochastic,
  optimization, neural-network, and custom-Python domains.
- `ExperimentParameter`, `ExperimentObservable`, and `ExperimentAssumption` with explicit source
  and review status.
- `ExperimentDraft`, `ExperimentVersion`, and `ExperimentPatchProposal` plus create/update/page
  request and response models needed by the HTTP API.
- Positive draft revisions and version numbers, SHA-256 content hashes, proposal lifecycle states,
  and strict immutable Pydantic models.

## Persistence and API behavior

Migration `0007_experiment_core` creates `experiments`, `experiment_drafts`,
`experiment_versions`, and `experiment_patch_proposals`. Version rows are append-only. Proposal
state changes are limited to pending-to-applied or pending-to-rejected, and proposal application
uses the proposal's expected draft revision in the same transaction as the draft update.

The API is rooted at `/api/v1` and adds:

- project-scoped experiment create/list;
- owner-scoped experiment and draft reads;
- compare-and-swap draft patching with stable `409 experiment_revision_conflict` errors;
- immutable version create/list with idempotent handling of repeated current-draft snapshots;
- proposal list/apply/reject endpoints without an LLM generation endpoint.

List endpoints are bounded to 100 items and use stable cursors. Mutations reuse existing session,
CSRF, validation-error, and forced-password-change protections.

## Delivery tasks

1. Freeze and generate shared contract `1.6` with focused red-green tests.
2. Add migration `0007`, persistence primitives, append-only/version/concurrency tests.
3. Add authenticated experiment services and routes with ownership and conflict tests.
4. Add feature-flagged Lab and Studio placeholders without changing Workbench behavior.
5. Add repeatable compatibility acceptance and setup documentation.

Each task is implemented in a bounded file set, committed independently, and accepted by a fresh
reviewer for both specification compliance and code quality. The final parent review covers the
entire branch. The branch remains local and work stops after Milestone 1.
