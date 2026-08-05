# Phase 8 browser gate evidence

Date: 2026-08-05 (Asia/Shanghai)

## Final browser run

```text
$ PLAYWRIGHT_BROWSERS_PATH=$PROJECT_ROOT/runtime/playwright-browsers \
    ./node_modules/.bin/playwright test -c tests/phase8/browser/playwright.config.ts

Running 1 test using 1 worker
1 passed (1.3m)
```

Runtime: Playwright 1.62.1 and Chrome for Testing 151.0.7922.34. All browsers, npm cache,
database, copied Web source, and generated artifacts remained under the project directory.

## Covered flow

- Two isolated users: login, mandatory first password change, logout and old-session rejection.
- Project creation, Prompt, offline ContentPlan generation, immutable ContentPlan v2 save,
  offline CodeVersion generation, Preview and Final submission.
- SSE queued-to-succeeded monitoring, forced network interruption, and server-observed
  `Last-Event-ID` replay cursor.
- Authenticated video metadata decode, thumbnail load, HTTP Range request, and MP4 download.
- Repeated page refresh plus API process termination/replacement with durable recovery.
- Cross-user project absence and existing API-level resource isolation matrix.
- 320, 768, 1024 and 1440 px overflow checks and login keyboard focus order.
- No uncaught page error and no first-party API response at status 400 or above.

## Gate-discovered regression

The restart scenario initially failed because `apps/web/src/hooks/workbench/use-workbench.ts`
rewrote the URL without preserving `job`. The browser test was retained as the regression proof;
the corrected run restored the Final job and artifacts after a new API process ID appeared.

## Security evidence

The initially installed Playwright 1.51.1 was rejected after npm audit reported
GHSA-7mvr-c777-76hp. The exact dependency was upgraded to 1.62.1, its matching Chromium was
installed project-locally, and the audit result became zero known vulnerabilities.

## Evidence files

- `desktop-workbench.png`
- `mobile-workbench.png`
- `playwright-report/index.html`
- runtime traces and failure screenshots are retained only for failed runs under the ignored
  `runtime/phase8-browser-gate/playwright-output` directory.
