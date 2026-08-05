# Phase 8 Browser Acceptance

**Status: PASS — isolated real-browser end-to-end gate completed on 2026-08-05.**

## Scope and safety

The gate ran only in `/home/developer/projects/Manim_project`. It used an isolated Web server,
SQLite database, artifact root, two temporary users, and offline deterministic ContentPlan and
Code providers. It made no DeepSeek request and did not mutate the live demo database. No commit,
push, or pull request was created.

## Results

| Gate | Result | Evidence |
| --- | --- | --- |
| Login and first-password change | Pass | Both temporary users were redirected through first-login password change. |
| Full two-user workflow | Pass | Both users completed Project → Prompt → ContentPlan v2 → CodeVersion → Preview → Final. |
| Owner isolation | Pass | User B could not see user A's project; existing API black-box cross-owner matrix remained green. |
| SSE reconnect | Pass | Chromium was forced offline and reconnected; the API observed a positive `Last-Event-ID`. |
| API restart recovery | Pass | The API process was terminated and restarted with a new PID; Session, Job and Artifact recovery passed. |
| Artifact playback and download | Pass | Video reached decoded metadata state, thumbnail loaded, HTTP Range delivery worked, and MP4 download completed. |
| Refresh recovery | Pass | Repeated refresh preserved the `job` query and restored the terminal Final job and artifacts. |
| Responsive and keyboard | Pass | 320, 768, 1024 and 1440 px checks had no horizontal overflow; login focus order passed. |
| Browser runtime errors | Pass | No page exception or failing first-party API response was observed. |
| Dependency audit | Pass | Playwright was upgraded to 1.62.1; npm reported zero vulnerabilities. |

## Regression fixed by the gate

The first restart run found that `loadProject()` removed the `job` query parameter. A first
refresh happened to recover the job, but a second refresh or service restart lost it. The
workbench now preserves the existing query while updating `project`, and the browser test proves
recovery after an API process replacement.

## Reproduction

```text
PLAYWRIGHT_BROWSERS_PATH=/home/developer/projects/Manim_project/runtime/playwright-browsers \
  ./node_modules/.bin/playwright test -c tests/phase8/browser/playwright.config.ts
```

The final run completed `1 passed (1.3m)`. The test copies the Web source into an ignored runtime
directory, starts isolated servers on ports 13000 and 18000, and resets only the gate database.

## Artifacts

- `benchmarks/phase8/browser/desktop-workbench.png`
- `benchmarks/phase8/browser/mobile-workbench.png`
- `benchmarks/phase8/browser/playwright-report/index.html`
- `benchmarks/phase8/browser/2026-08-05-gate-evidence.md`

Playwright's open-source Chromium build does not decode the H.264 codec used by the stored Manim
fixture. The playback assertion therefore uses a project-local VP9-in-MP4 fixture while retaining
real delivery headers, Range requests, authentication, integrity checks, UI playback, and download.
The existing Manim MP4 remains covered by artifact integrity and delivery tests.
