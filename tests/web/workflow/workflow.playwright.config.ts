import { defineConfig } from "@playwright/test";
import { randomUUID } from "node:crypto";

const root = process.cwd();
const initialPassword = `Browser1!${randomUUID()}`;

export default defineConfig({
  metadata: { initialPassword },
  testDir: ".",
  testMatch: "workflow.e2e.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  outputDir: `${root}/runtime/workflow-browser-gate/playwright-output`,
  reporter: "line",
  use: {
    baseURL: "http://localhost:13000",
    browserName: "chromium",
    launchOptions: {
      executablePath: process.env.MANIM_PLAYWRIGHT_CHROMIUM
        ?? `${root}/runtime/playwright-browsers/chromium-1234/chrome-linux64/chrome`,
    },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  webServer: [
    {
      command: `PHASE8_BROWSER_RESET=1 PHASE8_BROWSER_INITIAL_PASSWORD=${initialPassword} uv run uvicorn tests.phase8.browser.e2e_app:app --host 127.0.0.1 --port 18000`,
      cwd: root,
      url: "http://localhost:18000/api/v1/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "MANIM_WORKBENCH_API_URL=http://localhost:18000 npm --prefix apps/web run build && MANIM_WORKBENCH_API_URL=http://localhost:18000 npm --prefix apps/web run start -- --hostname 127.0.0.1 --port 13000",
      cwd: root,
      url: "http://localhost:13000/login",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
