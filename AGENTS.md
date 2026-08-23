# Repository Guidelines

## Project Structure & Module Organization

`apps/api` contains the FastAPI application; `apps/runner` owns queue coordination, Docker sandboxing, rendering, and visual diagnostics; `apps/web` is the Next.js interface. Shared Python and TypeScript contracts live in `packages/contracts`, with generated outputs under `packages/contracts/generated`. Database revisions are in `migrations/versions`. Put Manim examples in `reference_scenes/formula` or `reference_scenes/functions`. Tests are grouped by delivery phase under `tests/phase*`; Agent/IR tests live in `tests/agent` and `tests/ir`; browser and Web boundary tests live in `tests/phase8/browser` and `tests/web`. Evaluation data and evidence belong in `eval` and `benchmarks`; architecture and phase decisions belong in `docs`.

## Generation paths

The product goal is an LLM-driven scientific and technical animation system: natural-language
input is converted into constrained semantic plans, allowlisted computation, deterministic
animation programs, sandboxed renders, and downloadable video. There are two bounded internal
paths; do not describe them as one unrestricted live LLM Agent.

1. Teaching: Prompt → ContentPlan → SceneStoryboard → deterministic compiler → CodeVersion. The
   model fills constrained plan data; the default product path must not accept free Manim Scene
   Python. Formula and function expressions use the bounded expression compiler. Unsupported
   expressions, or geometry/3D plans without a validated Storyboard, fail closed instead of
   publishing a text-only placeholder video.
2. Animation Agent V2: one sentence → `IntentSpec` → allowlisted tools → AnimationIR 2.0 → deterministic compiler (`apps/api/.../compiler/manim.py`) → the same render sandbox. The model must not emit free Scene Python, lambdas, or live `np.exp` in the Scene.

The current one-sentence Intent resolver prefers an LLM that may only fill `IntentSpec` JSON (`fill_intent_from_provider`). Invalid JSON, fenced output, and Manim Python are rejected. Without `DEEPSEEK_API_KEY`, `resolve_intent` falls back to the keyword catalog in `resolve_intent_catalog`. CSV without a body returns `asset_required`. Paper/PDF reproduction runs `ode_compare` only when extracted text matches the closed Lotka–Volterra catalog with explicit coefficients; otherwise the run stays at `needs_confirmation` and does not invent equations. Spec source of truth: `docs/research/animation-agent-v2.md`.

P0 gold rates (≥85% first render / ≥97% final / ≥90% science) are measured by `scripts/agent_p0_acceptance.py` against `eval/agent_p0_gold.jsonl`. The research-matrix prompt without paper text still counts as `needs_confirmation`. The Manim compiler walks AnimationIR `data` / `states` / `objects` / `bindings` / `timeline` / `camera` and selects Scene / MovingCameraScene / ThreeDScene from dimension and camera ops, not from `VisualPattern`.

P1: immutable `AssetVersion` on `ToolRun` plus append-only `asset_versions` (`migrations/versions/0008_asset_versions.py`). CSV ingest limits columns, rows, and numeric dtypes; `.npy/.npz` load with `allow_pickle=False`. Teaching `UserAsset` (PNG/JPEG) is unchanged. After compile, a TIFA-style critic scores expression from IR/source/ToolRun; an optional provider may only fill `CriticJudgement` JSON. IR-level repair is at most one pass and never emits Scene Python. P1 gold (`eval/agent_p1_gold.jsonl`, 50–100 prompts) is gated by `scripts/agent_p1_acceptance.py` (expression ≥4.2/5, mean repair ≤1, full provenance).

P2: simulator plugins register in-process via `register_simulator` (the model still cannot name new ops). The second renderer is a deterministic Web JSON backend walking the same AnimationIR (`renderer_hint` `manim` | `web`); it is not Blender. Tool npz cache is `{op, params, input}` at `output_root`; IR compile cache is optional `cache_root`. P2 benchmark (`eval/agent_p2_benchmark.jsonl`, 100–300 prompts) is gated by `scripts/agent_p2_acceptance.py` (science ≥95%, unexpected `FAILED` <1%, every ready IR compiles on both backends). `scripts/agent_p2_trial.py` is a lab harness, not an external user study. OpenFOAM/FEniCS adapters and field trials are out of scope.

The local workbench does not use a login page. `settings_from_environment` defaults `auth_disabled` to true and `GET /auth/session` issues a `dev@local.test` session so owner isolation, CSRF, and cookies still work. `/login` and `/change-password` redirect to `/workbench`. Set `MANIM_WORKBENCH_AUTH_DISABLED=false` only if you need the Phase 8 login API path. Local Web should leave `NEXT_PUBLIC_API_URL` unset so the browser uses same-origin `/api` rewrites from `apps/web/next.config.ts`.

## Build, Test, and Development Commands

Run the repository from its WSL-native path, `/home/joshua/projects/Manim_project`.

```bash
uv sync --frozen                         # install locked Python dependencies
npm ci --ignore-scripts                  # install locked workspace dependencies
uv run python scripts/generate_contracts.py --check
uv run pytest -s -q                      # run the Python suite
uv run ruff check .                      # lint Python
npm run lint && npm run typecheck && npm run build
docker compose -f infra/compose.yaml up -d redis
uv run uvicorn manim_workbench_api.main:app --reload
uv run python -m manim_workbench_runner run
npm run dev:web
```

Apply schema changes with `uv run alembic upgrade head`. Use `scripts/phase8_acceptance.py` and `scripts/phase9_acceptance.py` for focused acceptance gates. Use `uv run python scripts/agent_p0_acceptance.py` for Animation Agent V2 P0 gold-set rates (add `--skip-render` without the Manim image). Use `uv run python scripts/agent_p1_acceptance.py` for P1 expression / repair / provenance gates. Use `uv run python scripts/agent_p2_acceptance.py` for P2 science / fail / cross-backend gates.

## Coding Style & Naming Conventions

Python targets 3.10, uses four-space indentation, type hints, and Ruff's 100-character line limit. Use `snake_case` for modules/functions and `PascalCase` for classes. TypeScript uses two spaces, `PascalCase` React components, `camelCase` functions, and kebab-case filenames. Keep contracts strict and immutable where established. Edit contract sources, then regenerate outputs; do not hand-edit generated files.

## Testing Guidelines

Pytest is the primary framework. Name files `test_*.py` and tests `test_<behavior>`. Place tests in the matching phase and layer (`integration`, `security`, `blackbox`, or `parent`). Every behavior change needs a focused regression test; security and rendering changes also need failure-path coverage. Run the focused test first, then the full suite and relevant acceptance script.

## Commit & Pull Request Guidelines

History follows Conventional Commit-style subjects such as `feat:`, `fix:`, `test:`, `docs:`, and `chore:`. Keep commits cohesive and use an imperative summary. Pull requests should explain scope and risk, link the task, list exact verification commands, call out migrations or contract changes, and include screenshots for UI work. Never commit `.env`, API keys, runtime databases, rendered videos, or sandbox artifacts. Preserve unrelated local changes; do not push or create a PR without explicit authorization.

## gstack

Use /browse from gstack for all web browsing. Never use mcp__claude-in-chrome__* tools.
Available skills: /office-hours, /plan-ceo-review, /plan-eng-review, /plan-design-review,
/design-consultation, /design-shotgun, /design-html, /review, /ship, /land-and-deploy,
/canary, /benchmark, /browse, /open-gstack-browser, /qa, /qa-only, /design-review,
/setup-browser-cookies, /setup-deploy, /setup-gbrain, /sync-gbrain, /retro, /investigate,
/document-release, /document-generate, /codex, /cso, /autoplan, /pair-agent, /careful, /freeze,
/guard, /unfreeze, /gstack-upgrade, /learn.
