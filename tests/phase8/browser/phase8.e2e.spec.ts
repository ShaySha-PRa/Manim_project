import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";

const initialPassword = "phase8-initial-password";
const readyPassword = "phase8-ready-password";
let replacementApi: ChildProcess | null = null;

test.afterEach(() => {
  replacementApi?.kill("SIGTERM");
  replacementApi = null;
});

async function signInAndChangePassword(page: Page, suffix: "a" | "b") {
  await page.goto("/login");
  await page.getByLabel("邮箱").fill(`teacher-${suffix}@example.test`);
  await page.getByLabel("密码").fill(initialPassword);
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page).toHaveURL(/\/change-password$/);
  await page.getByLabel("当前密码").fill(initialPassword);
  await page.locator("#new-password").fill(`${readyPassword}-${suffix}`);
  await page.getByRole("button", { name: "完成并进入工作台" }).click();
  await expect(page.getByRole("heading", { name: "数学动画工作台" })).toBeVisible();
}

async function completeWorkflow(page: Page, suffix: "a" | "b", exerciseReconnect = false) {
  const projectTitle = `Phase 8 浏览器项目 ${suffix.toUpperCase()}`;
  await page.getByLabel("新项目名称").fill(projectTitle);
  await page.getByRole("button", { name: "创建项目" }).click();
  await expect(page.locator("select").first()).toHaveValue(/.+/);

  await page.getByLabel("教学 Prompt").fill("用动态图像解释一次函数 y=kx 的斜率变化。 ");
  await page.getByLabel("函数可视化").check();
  await page.getByLabel("推导风格").selectOption("visual_intuition");
  await page.getByLabel("明确假设（每行一条，可选）").fill("学习者理解坐标系。");
  await page.getByRole("button", { name: "生成 ContentPlan" }).click();
  await expect(page.getByText("ContentPlan 已生成")).toBeVisible();
  await expect(page.getByRole("heading", { name: "ContentPlan" })).toBeVisible();

  await page.getByRole("button", { name: "保存为新版本" }).click();
  await expect(page.getByText("已保存 ContentPlan v2")).toBeVisible();
  await page.getByRole("button", { name: "生成 CodeVersion" }).click();
  await expect(page.getByText("已生成 CodeVersion v1")).toBeVisible();

  await page.getByRole("button", { name: "提交预览" }).click();
  await expect(page.getByText(/预览 · (queued|succeeded)/)).toBeVisible();
  if (exerciseReconnect) {
    const jobId = new URL(page.url()).searchParams.get("job");
    expect(jobId).not.toBeNull();
    const firstEventId = await page.evaluate((id) => new Promise<number>((resolve, reject) => {
      const source = new EventSource(`http://localhost:18000/api/v1/render-jobs/${id}/events`, {
        withCredentials: true,
      });
      (window as unknown as { __phase8GateSource: EventSource }).__phase8GateSource = source;
      source.addEventListener("render_job", (event) => resolve(Number(event.lastEventId)));
      source.onerror = () => reject(new Error("gate EventSource failed before first event"));
    }), jobId);
    expect(firstEventId).toBeGreaterThanOrEqual(1);
    await page.context().setOffline(true);
    await page.waitForTimeout(750);
    await page.context().setOffline(false);
  }
  await expect(page.getByText("预览 · succeeded")).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("video")).toBeVisible();
  await expect(page.getByAltText("渲染视频缩略图")).toBeVisible();
  const mediaState = await page.locator("video").evaluate((video: HTMLVideoElement) => ({
    error: video.error ? { code: video.error.code, message: video.error.message } : null,
    networkState: video.networkState,
    readyState: video.readyState,
  }));
  expect(mediaState.error, JSON.stringify(mediaState)).toBeNull();
  expect(mediaState.readyState, JSON.stringify(mediaState)).toBeGreaterThanOrEqual(1);

  await page.getByRole("button", { name: "提交终渲" }).click();
  await expect(page.getByText("终渲 · succeeded")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("link", { name: "下载视频" })).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "下载视频" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.mp4$/);

  await page.reload();
  await expect(page.getByText("终渲 · succeeded")).toBeVisible();
  await expect(page.locator("video")).toBeVisible();
  return projectTitle;
}

async function restartApi(page: Page): Promise<void> {
  const beforeResponse = await page.request.get("http://localhost:18000/api/v1/health");
  const before = await beforeResponse.json() as { process_id: number };
  const shutdown = await page.request.post("http://localhost:18000/__phase8_gate__/shutdown");
  expect(shutdown.ok()).toBe(true);
  await page.waitForTimeout(500);
  replacementApi = spawn(
    "uv",
    ["run", "uvicorn", "tests.phase8.browser.e2e_app:app", "--host", "127.0.0.1", "--port", "18000"],
    {
      cwd: process.cwd(),
      env: { ...process.env, PHASE8_BROWSER_RESET: "0" },
      stdio: "ignore",
    },
  );
  await expect.poll(async () => {
    try {
      const response = await page.request.get(
        `http://localhost:18000/api/v1/health?nonce=${Date.now()}`,
        { headers: { "Cache-Control": "no-cache" } },
      );
      if (!response.ok()) return false;
      const current = await response.json() as { process_id: number };
      return current.process_id !== before.process_id;
    } catch {
      return false;
    }
  }, { timeout: 20_000 }).toBe(true);
}

async function assertSecondUserCannotSeeFirstProject(context: BrowserContext, firstTitle: string) {
  const page = await context.newPage();
  await signInAndChangePassword(page, "b");
  await expect(page.getByText(firstTitle)).toHaveCount(0);
  await completeWorkflow(page, "b");
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({
    animations: "disabled",
    fullPage: true,
    path: `${process.cwd()}/benchmarks/phase8/browser/mobile-workbench.png`,
  });
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/workbench");
  await expect(page).toHaveURL(/\/login$/);
  await page.reload();
  await expect(page.locator("#email")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.locator("#password")).toBeFocused();
}

test("two users complete the offline browser workflow with recovery and isolation", async ({ browser }) => {
  const pageErrors: string[] = [];
  const failedApiResponses: string[] = [];
  const sseRequests: Array<Record<string, string>> = [];
  const firstContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const firstPage = await firstContext.newPage();
  firstPage.on("pageerror", (error) => pageErrors.push(error.message));
  firstPage.on("response", (response) => {
    const pendingQualityReport =
      response.status() === 404 && /\/render-jobs\/[^/]+\/quality-report$/.test(response.url());
    if (response.url().includes("/api/") && response.status() >= 400 && !pendingQualityReport) {
      failedApiResponses.push(`${response.status()} ${response.url()}`);
    }
  });
  firstPage.on("request", (request) => {
    if (request.url().includes("/events")) sseRequests.push(request.headers());
  });
  await signInAndChangePassword(firstPage, "a");
  const firstTitle = await completeWorkflow(firstPage, "a", true);
  expect(sseRequests.length).toBeGreaterThanOrEqual(2);
  const reconnectEvidence = await firstPage.request.get(
    "http://localhost:18000/__phase8_gate__/sse-reconnect-evidence",
  );
  expect(reconnectEvidence.ok()).toBe(true);
  const reconnectPayload = await reconnectEvidence.json() as { last_event_ids: number[] };
  expect(reconnectPayload.last_event_ids.some((cursor) => cursor >= 1)).toBe(true);
  await firstPage.screenshot({
    animations: "disabled",
    fullPage: true,
    path: `${process.cwd()}/benchmarks/phase8/browser/desktop-workbench.png`,
  });
  for (const width of [768, 1024]) {
    await firstPage.setViewportSize({ width, height: 900 });
    await expect.poll(() => firstPage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }

  await restartApi(firstPage);
  await firstPage.reload();
  await expect(firstPage.getByText("终渲 · succeeded")).toBeVisible();
  await expect(firstPage.locator("video")).toBeVisible();

  const secondContext = await browser.newContext({ viewport: { width: 320, height: 800 } });
  await assertSecondUserCannotSeeFirstProject(secondContext, firstTitle);
  expect(pageErrors).toEqual([]);
  expect(failedApiResponses).toEqual([]);
  await secondContext.close();
  await firstContext.close();
});
