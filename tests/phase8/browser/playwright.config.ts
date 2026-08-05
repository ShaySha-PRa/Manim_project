import { defineConfig } from "@playwright/test";

const root = "/home/developer/projects/Manim_project";

export default defineConfig({
  testDir: ".",
  testMatch: "phase8.e2e.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  outputDir: `${root}/runtime/phase8-browser-gate/playwright-output`,
  reporter: [["line"], ["html", { outputFolder: `${root}/benchmarks/phase8/browser/playwright-report`, open: "never" }]],
  use: {
    baseURL: "http://localhost:13000",
    browserName: "chromium",
    launchOptions: {
      executablePath: `${root}/runtime/playwright-browsers/chromium-1234/chrome-linux64/chrome`,
    },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  webServer: [
    {
      command: "PHASE8_BROWSER_RESET=1 uv run uvicorn tests.phase8.browser.e2e_app:app --host 127.0.0.1 --port 18000",
      cwd: root,
      url: "http://localhost:18000/api/v1/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "uv run python tests/phase8/browser/prepare_isolated_web.py && cd runtime/phase8-browser-web && NEXT_PUBLIC_API_URL=http://localhost:18000 ../../node_modules/.bin/next dev --hostname 127.0.0.1 --port 13000",
      cwd: root,
      url: "http://localhost:13000/login",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
