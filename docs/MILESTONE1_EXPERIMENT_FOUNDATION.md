# Milestone 1: Experiment Foundation

## Purpose and non-goals

Milestone 1 adds the compatibility foundation for interactive scientific experiments while
leaving the Phase 9 teaching-video workflow unchanged. It introduces experiment contracts,
persistence, authenticated APIs, and feature-flagged Lab and Studio placeholders. It does not
execute scientific models, open WebSockets, call DeepSeek for experiment patches, or render
interactive scenes. The placeholders must explicitly say that runtime/interactive rendering is
not enabled in Milestone 1.

## Global constraints

- Contract schema version is `1.6`. Existing ContentPlan, CodeVersion, RenderJob, quality, auth,
  project, workspace, delivery, and every other pre-M1 request/response field semantics remain
  unchanged. The only permitted existing API observable change is health
  `contract_schema_version: Literal["1.6"]`.
- Existing `/workbench` behavior, query parameters, authentication, first-password-change flow,
  API routes, user/project data, and rendered-video access remain compatible. Workbench files and
  behavior are not changed by the Lab or Studio work.
- New `/lab` and `/studio` navigation is disabled by default and controlled independently by
  `NEXT_PUBLIC_EXPERIMENT_LAB_ENABLED` and `NEXT_PUBLIC_STUDIO_ENABLED`.
- Experiments belong to an existing project and its owner. Reads and writes always scope by both
  resource ID and authenticated owner ID.
- A project has many experiments. An experiment has one mutable draft and immutable version
  snapshots. Draft updates use an integer revision and compare-and-swap semantics.
- Patch proposals are stored review objects. Milestone 1 can list, apply, and reject stored
  proposals but does not create or generate them with an LLM.
- No migration before `0007` may be modified. Upgrade preserves all existing records; downgrade
  removes only Milestone 1 tables, indexes, and triggers.
- No new runtime dependency is required for Milestone 1.
- Milestone 1 formally uses `tests/milestone1/**` as an explicit repository-layout exception for
  this cross-phase platform foundation. Existing phase test trees remain unchanged.

## 1. Frozen shared contract

`ModelSpec` is a stable envelope with a domain discriminator and opaque, JSON-compatible domain
payload. The shared layer validates envelope size and shape but does not encode heat-transfer,
geometry, FEM, neural-network, or renderer-specific fields. Domain plugins introduced in later
milestones own those payload schemas.

### Wire enums and bounded JSON

| Type | Exact wire values or definition |
| --- | --- |
| `ExperimentDomainKind` | `generic`, `geometry`, `ode`, `pde`, `fem`, `stochastic`, `optimization`, `neural_network`, `custom_python` |
| `AssumptionSource` | `user`, `model`, `import`, `system` |
| `AssumptionStatus` | `proposed`, `accepted`, `rejected` |
| `ExperimentPatchProposalStatus` | `pending`, `applied`, `rejected` |
| `ExperimentPatchOperationKind` | `add`, `replace`, `remove` |
| `JsonValue` | Recursive `null`/string/finite number/boolean/array/object value. Object values are `Readonly<Record<string, JsonValue>>` in generated TypeScript; booleans remain booleans and are never coerced to numbers. This is the only bounded escape hatch. |

`JsonValue` has maximum nesting depth 32. Its canonical JSON representation must be no more
than 200,000 UTF-8 bytes where limits and hashes use exactly:

```python
json.dumps(
    value,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
).encode("utf-8")
```

All floats must be finite. The validator rejects NaN, infinity, values beyond the byte limit, and
values beyond the depth limit. Recursive arrays and objects are bounded in Python, JSON Schema,
and TypeScript; generated TypeScript contains no `any`, `unknown`, or unconstrained map, and JSON
Schema never emits `additionalProperties: true`.

### Public fields and validation

`ShortText` means a required non-empty string of 1–200 characters. `RelativePath` means a
required string of 1–500 characters using the existing repository relative-path safety rule:
replace backslashes with `/` for validation, reject a leading `/` and any `..` path segment, and
retain the original safe relative value. All models use strict extra-field rejection and frozen
Pydantic model behavior.

| Public type | Required fields | Optional/default fields and exact validation |
| --- | --- | --- |
| `ModelSpec` | `schema_version: Literal["1.0"]`, `domain_kind: ExperimentDomainKind`, `plugin_id`, `plugin_version`, `payload` | `plugin_id` matches `^[a-z][a-z0-9_.-]{2,99}$`; `plugin_version` is 1–50 characters; `payload` is a JSON object; its canonical JSON representation is at most 200,000 UTF-8 bytes and observes the bounded `JsonValue` rules. |
| `ExperimentParameter` | `key`, `label`, `value: JsonValue` | `unit: string | None`, at most 100 characters; `editable: bool = True`; `key` matches `^[A-Za-z][A-Za-z0-9_.-]{0,99}$`; `label` is `ShortText`. |
| `ExperimentObservable` | `key`, `label` | `description: string | None`, at most 2,000 characters; `unit: string | None`, at most 100 characters; `key` uses the same identifier regex and `label` is `ShortText`. |
| `ExperimentAssumption` | `id: UUID`, `statement`, `source: AssumptionSource`, `status: AssumptionStatus`, `created_at` | `statement` is a required non-empty string of at most 2,000 characters. |
| `ExperimentCodeFile` | `path: RelativePath`, `language: Literal["python"]`, `content` | `content` is a required string of at most 200,000 characters; duplicate paths are rejected within a draft. |
| `Experiment` | `id: UUID`, `project_id: UUID`, `owner_id: UUID`, `title: ShortText`, `created_at` | `archived_at: datetime | None`. |
| `ExperimentCreateRequest` | `title: ShortText` | `domain_kind: ExperimentDomainKind = generic`. |
| `ExperimentPage` | `items: tuple[Experiment, ...]` | At most 100 items and an optional UUID `cursor`. |
| `ExperimentDraft` | `experiment_id`, `project_id`, `owner_id`, positive integer `revision`, `model_spec`, `parameters`, `observables`, `assumptions`, `updated_at` | `parameters` at most 200; `observables` at most 200; `assumptions` at most 100; `visualization` is a JSON object defaulting to `{}`; `code_files` at most 20. |
| `ExperimentDraftUpdateRequest` | Positive integer `expected_revision` | Optional replacement fields: `model_spec`, `parameters`, `observables`, `assumptions`, `visualization`, `code_files`. At least one replacement field is required; omitted and explicitly empty tuple/object replacements are distinct, and an explicitly empty replacement is valid. |
| `ExperimentVersion` | UUID identity and ownership fields (`id`, `experiment_id`, `project_id`, `owner_id`), positive `version`, positive `draft_revision`, all six snapshot fields, `content_hash`, `created_at` | `parent_version_id: UUID | None`; version 1 must have no parent and later versions must have a parent. The six snapshot fields are `model_spec`, `parameters`, `observables`, `assumptions`, `visualization`, and `code_files`; `content_hash` is a lowercase SHA-256 hex string. |
| `ExperimentVersionCreateRequest` | Positive integer `expected_revision` | None. |
| `ExperimentVersionPage` | `items: tuple[ExperimentVersion, ...]` | At most 100 items and an optional positive integer cursor. |
| `ExperimentPatchOperation` | `kind: ExperimentPatchOperationKind`, `path` | `path` is a JSON Pointer of 1–500 characters beginning with `/`; optional `value: JsonValue`. `add` and `replace` require `value`; `remove` forbids it. |
| `ExperimentPatchProposal` | UUID identity and ownership fields, positive `expected_revision`, `status`, `operations`, `assumptions`, `source: AssumptionSource`, `created_at` | `operations` has 1–100 items; `assumptions` has at most 100; `resolved_at: datetime | None` is absent for pending and required for applied/rejected. |
| `ExperimentPatchProposalPage` | `items: tuple[ExperimentPatchProposal, ...]` | At most 100 items and an optional UUID cursor. |
| `ExperimentPatchProposalApplyRequest` | Positive integer `expected_revision` | None. |
| `ExperimentPatchProposalRejectRequest` | Positive integer `expected_revision` | Optional `reason`, at most 2,000 characters. |

Every public type is exported from `manim_workbench_contracts.__init__`. Every concrete
request/response model is included in `CONTRACT_MODELS`. Python models, generated TypeScript, and
generated JSON Schema are committed only through `uv run python scripts/generate_contracts.py`;
generated artifacts are not hand-edited.

Contract tests must prove that all existing models serialize identically except for the top-level
schema version, that strict extra-field rejection and frozen behavior remain intact, that nested
finite JSON and all limit failures behave as above, that draft updates distinguish omission from
explicit empty replacements, that duplicate code paths fail, and that version-parent,
patch-operation, and proposal-lifecycle validators cover both success and failure.

## 2. Persistence schema and invariants

Migration `0007_experiment_core` creates exactly four M1 tables. It must not alter pre-0007
objects.

| Table | Columns | Keys, FKs, constraints, and triggers |
| --- | --- | --- |
| `experiments` | `id` PK, `project_id`, `owner_id`, `title`, `domain_kind`, `created_at`, `archived_at` | FKs to project and user; `UNIQUE(id, project_id, owner_id)`; trigger rejects insert/update when `project.owner_id` differs from `owner_id`; indexes support `owner_id`, `project_id`, and `id`. M1 exposes no delete endpoint. |
| `experiment_drafts` | `experiment_id` PK plus `project_id`, `owner_id`, `revision`, `model_spec_json`, `parameters_json`, `observables_json`, `assumptions_json`, `visualization_json`, `code_files_json`, `updated_at` | Composite FK `(experiment_id, project_id, owner_id)` to `experiments` with `ON DELETE CASCADE`; `revision >= 1`; the PK enforces exactly one draft per experiment. |
| `experiment_versions` | `id` PK, `experiment_id`, `project_id`, `owner_id`, `version`, `parent_version_id`, `draft_revision`, `model_spec_json`, `parameters_json`, `observables_json`, `assumptions_json`, `visualization_json`, `code_files_json`, `content_hash`, `created_at` | Composite experiment FK with `ON DELETE CASCADE`; self-FK `(parent_version_id, experiment_id)` to `UNIQUE(id, experiment_id)`; `UNIQUE(experiment_id, version)`; `UNIQUE(experiment_id, content_hash)`; positive `version` and `draft_revision`; first/later parent invariant; update and delete append-only triggers. |
| `experiment_patch_proposals` | `id` PK, `experiment_id`, `project_id`, `owner_id`, `expected_revision`, `status`, `operations_json`, `assumptions_json`, `source`, `created_at`, `resolved_at`, `rejection_reason` | Composite experiment FK with `ON DELETE CASCADE`; positive `expected_revision`; pending has no resolution/reason; applied requires `resolved_at` and no rejection reason; rejected requires `resolved_at` and may have a reason; trigger permits only `pending -> applied/rejected` and forbids all other content changes. |

The ownership trigger is authoritative even if an application caller supplies matching IDs. All
repository reads apply owner scoping, and all writes use the same owner-scoped predicates as the
HTTP layer.

Downgrade drops the proposal transition trigger and version append-only triggers first, then drops
`experiment_patch_proposals`, `experiment_versions`, `experiment_drafts`, `experiments`, and
their M1 indexes. It never alters pre-0007 objects or data.

### Required transaction semantics

| Operation | One-transaction algorithm and observable result |
| --- | --- |
| Create experiment | Create the experiment and revision-1 draft atomically. The initial `ModelSpec` uses the selected domain, `plugin_id="core.generic"`, `plugin_version="1.0"`, empty payload/collections, and empty visualization/code files. |
| Replace draft | Execute one `UPDATE ... WHERE experiment_id, owner_id, revision=expected` and set revision to `expected + 1`. Zero rows become `experiment_revision_conflict`, except a hidden/not-found resource is resolved first as `experiment_not_found`. |
| Snapshot version | In one write transaction, read the draft and latest version, require the expected revision, hash only the six editable snapshot fields with the canonical JSON algorithm above, and insert the next version/parent. If `(experiment_id, content_hash)` exists, return it without insert. If a concurrent insert hits either unique constraint, re-read: same hash returns the existing resource; a different hash returns `experiment_revision_conflict`. |
| Apply proposal | In one write transaction require pending status and request expected revision equal to proposal expected revision and current draft revision; apply operations sequentially; validate the resulting editable draft; CAS-update the draft; then mark the proposal applied with `resolved_at`. Concurrent apply/reject has one winner; the loser returns `experiment_proposal_resolved`. A still-pending stale proposal returns revision conflict. |
| Reject proposal | In one transaction require pending status and matching request/proposal/current revision, then set rejected with `resolved_at` and optional reason. Concurrent apply/reject has one winner and the loser returns `experiment_proposal_resolved`. |

JSON Patch is the RFC 6901 pointer plus the RFC 6902 `add`/`replace`/`remove` subset. Paths may
target only `/model_spec`, `/parameters`, `/observables`, `/assumptions`, `/visualization`,
`/code_files`, or descendants. Identity, ownership, revision, and timestamps are never
patchable. Standard escaped tokens and array indexes apply; `-` is allowed only for `add`.
Missing parents/targets, invalid indexes, forbidden roots, invalid operations, or an invalid final
draft yield `experiment_patch_invalid`.

## 3. HTTP endpoint and error contract

All routes are rooted at `/api/v1`. Every read uses a ready-session principal. Every write uses a
mutating principal and the existing CSRF/origin checks; existing forced-password-change behavior
is inherited.

### Endpoint matrix

| Method and path | Request/query | Response and status | Pagination or behavior |
| --- | --- | --- | --- |
| `POST /api/v1/projects/{project_id}/experiments` | `ExperimentCreateRequest` | `Experiment`, `201` | Project and owner scoped. |
| `GET /api/v1/projects/{project_id}/experiments` | `cursor: UUID | None`, `limit: 1..100`, default `20` | `ExperimentPage`, `200` | Order by `id ASC`; return rows with `id > cursor`. |
| `GET /api/v1/experiments/{experiment_id}` | None | `Experiment`, `200` | Owner scoped. |
| `GET /api/v1/experiments/{experiment_id}/draft` | None | `ExperimentDraft`, `200` | Owner scoped. |
| `PATCH /api/v1/experiments/{experiment_id}/draft` | `ExperimentDraftUpdateRequest` | `ExperimentDraft`, `200` | Compare-and-swap by expected revision. |
| `POST /api/v1/experiments/{experiment_id}/versions` | `ExperimentVersionCreateRequest` | New `ExperimentVersion`, `201`; same content hash returns existing resource with `200` | Idempotent current-draft snapshot. |
| `GET /api/v1/experiments/{experiment_id}/versions` | `cursor: positive integer | None`, `limit` default `20`, max `100` | `ExperimentVersionPage`, `200` | Newest version first; return rows with `version < cursor`. |
| `GET /api/v1/experiments/{experiment_id}/patch-proposals` | `cursor: UUID | None`, `limit` default `20`, max `100` | `ExperimentPatchProposalPage`, `200` | Order by `id ASC`. |
| `POST /api/v1/experiments/{experiment_id}/patch-proposals/{proposal_id}/apply` | `ExperimentPatchProposalApplyRequest` | Updated `ExperimentDraft`, `200` | Proposal and experiment must be owner scoped. |
| `POST /api/v1/experiments/{experiment_id}/patch-proposals/{proposal_id}/reject` | `ExperimentPatchProposalRejectRequest` | Updated `ExperimentPatchProposal`, `200` | Optional rejection reason; proposal transition is transactional. |

There is no proposal create or generate endpoint in M1. There is no experiment delete endpoint in
M1. All list limits are bounded to 100 and all cursors are stable and owner scoped.

### Stable errors

| Status | Code | Condition |
| --- | --- | --- |
| `401` / `403` | Existing auth codes | Existing authentication, authorization, CSRF/origin, and forced-password-change semantics remain unchanged. |
| `422` | `validation_error` | Request validation fails, including malformed fields or invalid pagination values. |
| `404` | `project_not_found` | Project is absent or belongs to another owner for project collection access. |
| `404` | `experiment_not_found` | Experiment is absent or belongs to another owner. |
| `404` | `experiment_proposal_not_found` | Proposal is absent, belongs to another experiment, or belongs to another owner. |
| `409` | `experiment_revision_conflict` | Expected revision is stale, or a concurrent non-idempotent version insert loses the re-read race. |
| `409` | `experiment_proposal_resolved` | Proposal is already applied or rejected, including the losing concurrent apply/reject request. |
| `422` | `experiment_patch_invalid` | Stored operations are forbidden/inapplicable, or the final draft is invalid. |

## 4. Web feature flags and routes

Both flags default to disabled unless their exact value is lowercase `true`. They are independent;
one flag must not enable or disable the other.

| Flag | Navigation and direct-route behavior when disabled | Behavior when enabled |
| --- | --- | --- |
| `NEXT_PUBLIC_EXPERIMENT_LAB_ENABLED` | Omit only the Lab nav link; direct `/lab` calls Next.js `notFound()` and returns 404. | Show the Lab nav link and load a protected placeholder. |
| `NEXT_PUBLIC_STUDIO_ENABLED` | Omit only the Studio nav link; direct `/studio` calls Next.js `notFound()` and returns 404. | Show the Studio nav link and load a protected placeholder. |

An enabled direct route uses the same session recovery behavior as Workbench: unauthenticated
users go to `/login`, and users who must change their password go to `/change-password`. The
placeholder is protected even when reached directly. It explicitly states that runtime/interactive
rendering is not enabled in Milestone 1. Do not change Workbench files or behavior.

## 5. Task acceptance matrix

Each task has a bounded file set, is committed independently, and must pass a fresh reviewer for
specification compliance and code quality. The final parent review covers the entire branch. The
review-package filename observation requires no code change; future review packages record resolved
target SHAs.

### Task 1 — Shared experiment contracts

- Dependencies: the existing contracts, generator, and pre-M1 contract tests; no production API or
  migration dependency.
- Exact file scope: `packages/contracts/**` and `tests/milestone1/contracts/**`. Generated
  TypeScript and JSON Schema are committed, but only through the repository generator.
- Success assertions: schema version is `1.6`; every public type above is exported and every
  concrete request/response model is in `CONTRACT_MODELS`; existing models serialize identically
  except for the top-level version; strict/frozen behavior remains; recursive JSON accepts nested
  finite values and rejects NaN/infinity, depth >32, and canonical bytes >200,000; generated
  TypeScript has no `any`/`unknown`/unconstrained maps and schema has no
  `additionalProperties: true`; draft omission/empty replacement, duplicate code paths, version
  parents, patch operations, and proposal lifecycle all have success and failure coverage.
- Focused commands and gate order:

  ```bash
  uv run pytest -s -q tests/milestone1/contracts tests/phase3/test_generated_contracts.py \
    tests/phase9/parent/test_phase9_contracts.py
  uv run python scripts/generate_contracts.py
  uv run pytest -s -q tests/milestone1/contracts tests/phase3/test_generated_contracts.py \
    tests/phase9/parent/test_phase9_contracts.py
  uv run python scripts/generate_contracts.py --check
  ```

### Task 2 — Experiment persistence

- Dependencies: Task 1 contract types; existing migration head `0006` and repository transaction
  helpers. Existing migrations are read-only.
- Exact file scope: the new `0007_experiment_core` migration, `apps/api` experiment persistence
  files, and `tests/milestone1/persistence/**`.
- Success assertions: all four tables, composite ownership FKs, indexes, unique constraints,
  ownership trigger, append-only version triggers, proposal transition trigger, parent invariant,
  exactly-one-draft invariant, CAS semantics, idempotent snapshot semantics, JSON Patch subset,
  downgrade ordering, and preservation of pre-0007 data match Sections 2 and 3.
- Focused commands: run `uv run pytest -s -q tests/milestone1/persistence` with every database
  path supplied by the test fixture as a temporary SQLite path; exercise migration upgrade,
  repository transactions, concurrent conflict paths, and downgrade/re-upgrade in that suite.

### Task 3 — Experiment HTTP API

- Dependencies: Tasks 1–2; existing ready-session/mutating-principal, CSRF/origin, ownership,
  validation, and forced-password-change middleware.
- Exact file scope: the experiment API module, API application router registration, the health
  `contract_schema_version` update, and `tests/milestone1/api/**`.
- Success assertions: every endpoint in the matrix has the stated request, response, status,
  owner boundary, cursor order, limit, idempotency, revision conflict, proposal lifecycle, and
  stable error behavior; there is no proposal-generation endpoint; all pre-M1 API definitions and
  observables remain unchanged except health version `1.6`.
- Focused commands: run `uv run pytest -s -q tests/milestone1/api`, then
  `uv run python scripts/generate_contracts.py --check`; include unauthenticated,
  must-change-password, cross-owner, stale-revision, invalid-patch, and concurrent proposal
  apply/reject cases.

### Task 4 — Feature-flagged Web entries

- Dependencies: Task 3 route contract and the existing Workbench session recovery behavior.
- Exact file scope: the two new Lab/Studio routes, navigation feature-flag handling, shared CSS
  needed by the placeholders, and `tests/web/milestone1/**`. Workbench files are out of scope.
- Success assertions: flags default false and enable independently only for exact lowercase
  `true`; disabled nav links are omitted; disabled direct routes return 404 via `notFound()`;
  enabled direct routes enforce `/login` and `/change-password` recovery; placeholders explicitly
  state that runtime/interactive rendering is not enabled; existing Workbench tests and behavior
  are unchanged.
- Focused commands: run the Web milestone tests with the repository's Playwright configuration,
  focused as:

  ```bash
  npx playwright test --config tests/phase8/browser/playwright.config.ts \
    tests/web/milestone1 tests/web/workbench
  npm run lint
  npm run typecheck
  ```

### Task 5 — Compatibility acceptance and documentation

- Dependencies: Tasks 1–4, migration `0007`, generated artifacts, and the existing Phase 8/9
  acceptance harnesses.
- Exact file scope: the new acceptance script and tests, `.env.example`, `README.md`, and this
  Milestone 1 documentation. The acceptance workflow must not access the developer's normal
  database.
- Success assertions: the acceptance harness uses temporary SQLite paths only and covers all of
  the following:

  1. Upgrade an empty database to `0007`.
  2. Populate a `0006` database with representative rows in `users`, `projects`, prompt/content/
     code versions, `render_jobs`, `artifacts`, `sessions`, `job_events`, and
     `quality_reports`/diagnostics/ratings. Record counts and stable identifying values before
     upgrade and prove every one is unchanged after upgrade.
  3. Cover experiment create/read/update/conflict/snapshot/idempotency/ownership and all proposal
     state paths.
  4. Downgrade to `0006`, prove only the four M1 tables/triggers/indexes disappear, prove the
     representative old data remains, and re-upgrade to `0007` successfully.
  5. Use a schema `1.5` compatibility fixture with a per-definition SHA-256 hash for every
     pre-M1 `$defs` entry, proving `1.6` changed only the top-level version plus additive
     experiment definitions.
  6. Prove flags default false, independent enablement, false direct-route 404, and enabled auth
     redirects.
  7. Run existing focused auth/project/workspace/delivery/job/content/code/quality suites,
     `tests/web/workbench`, Phase 8 acceptance, Phase 9 acceptance, the contract check, Ruff,
     full pytest, and Web lint/typecheck/build. Live Preview rendering is not required for this
     foundation, but its API and tests must remain unchanged.

- Focused and full commands:

  ```bash
  uv run pytest -s -q tests/milestone1
  uv run pytest -s -q tests/phase8/auth tests/phase8/projects \
    tests/phase8/parent/test_workspace_boundary.py tests/phase8/delivery \
    tests/phase5 tests/phase6 tests/phase7 tests/phase9 tests/web/workbench
  uv run python scripts/phase8_acceptance.py
  uv run python scripts/phase9_acceptance.py
  uv run python scripts/generate_contracts.py --check
  uv run ruff check .
  uv run pytest -s -q
  npm run lint && npm run typecheck && npm run build
  ```

All acceptance commands run from `/home/joshua/projects/Manim_project`, or the active WSL worktree,
and the branch remains local after Milestone 1.
