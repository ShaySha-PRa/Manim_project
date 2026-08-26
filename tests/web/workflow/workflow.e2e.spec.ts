import { expect, test, type BrowserContext, type Page, type Request } from "@playwright/test";
import { randomUUID } from "node:crypto";

const readyPassword = `Ready1!${randomUUID()}`;

async function signIn(page: Page, suffix: "a" | "b", initialPassword: string) {
  const origin = "http://localhost:13000";
  const login = await page.request.post(`${origin}/api/v1/auth/login`, {
    headers: { Origin: origin },
    data: { email: `teacher-${suffix}@example.test`, password: initialPassword },
  });
  expect(login.ok(), await login.text()).toBe(true);
  const loginPayload = await login.json() as { csrf_token: string };
  const changed = await page.request.post(`${origin}/api/v1/auth/change-password`, {
    headers: { Origin: origin, "X-CSRF-Token": loginPayload.csrf_token },
    data: {
      current_password: initialPassword,
      new_password: `${readyPassword}-${suffix}`,
    },
  });
  expect(changed.ok(), await changed.text()).toBe(true);
  await page.goto("/workbench");
  await expect(page.getByRole("heading", { name: "科学与技术动画工作台" })).toBeVisible();
}

async function createProject(page: Page) {
  await page.getByLabel("新项目名称").fill("可组合场景浏览器验收");
  await page.getByRole("button", { name: "创建项目" }).click();
  await expect(page.getByRole("option", { name: "可组合场景浏览器验收" })).toBeAttached();
  await page.getByRole("link", { name: "场景工作流" }).click();
  await expect(page.getByRole("heading", { name: "把自然语言场景组合成完整视频" })).toBeVisible();
}

function sceneRunRequests(requests: Request[]) {
  return requests.filter((request) => (
    request.method() === "POST" && /\/scene-block-versions\/[^/]+\/runs$/.test(request.url())
  ));
}

async function assertOwnerBoundary(
  context: BrowserContext,
  workflowId: string,
  versionId: string,
  initialPassword: string,
) {
  const page = await context.newPage();
  await signIn(page, "b", initialPassword);
  for (const path of [
    `/api/v1/video-workflows/${workflowId}`,
    `/api/v1/workflow-versions/${versionId}`,
  ]) {
    const response = await page.request.get(`http://localhost:13000${path}`);
    expect(response.status()).toBe(404);
    expect(await response.text()).not.toContain(workflowId);
  }
}

test("linear workflow preserves clips across edit, reorder, refresh, and owner isolation", async ({ browser }, testInfo) => {
  const initialPassword = String(testInfo.config.metadata.initialPassword ?? "");
  expect(initialPassword).not.toBe("");
  const requests: Request[] = [];
  const failedApi: string[] = [];
  const pageErrors: string[] = [];
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  page.on("request", (request) => {
    if (request.url().includes("/api/")) requests.push(request);
  });
  page.on("response", (response) => {
    if (response.url().includes("/api/") && response.status() >= 400) {
      failedApi.push(`${response.status()} ${response.url()}`);
    }
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await signIn(page, "a", initialPassword);
  await createProject(page);
  const cards = page.locator("article");
  await expect(cards).toHaveCount(2);
  await cards.nth(0).getByLabel("标题").fill("公式导入");
  await cards.nth(0).getByLabel("自然语言场景描述").fill("解释 Lorenz 方程中的三个参数。");
  await cards.nth(0).getByLabel("生成路径").selectOption("teaching");
  await cards.nth(1).getByLabel("标题").fill("吸引子轨迹");
  await cards.nth(1).getByLabel("自然语言场景描述").fill("展示 Lorenz 轨迹形成蝴蝶吸引子。");
  await cards.nth(1).getByLabel("生成路径").selectOption("scientific");
  await page.getByRole("button", { name: "保存新版本" }).click();
  await expect(page.getByText("已保存 Workflow v1。")).toBeVisible();

  await page.getByRole("button", { name: "生成所有未完成 Preview" }).click();
  await expect(page.locator("article video")).toHaveCount(2);
  expect(sceneRunRequests(requests)).toHaveLength(2);
  await page.getByRole("button", { name: "合成整片 Preview" }).click();
  await expect(page.getByText("workflow-browser-gate-v1")).toBeAttached();
  await expect(page.getByRole("link", { name: "下载完整 MP4" })).toBeVisible();

  const firstVersionId = new URL(page.url()).searchParams.get("version");
  const workflowId = new URL(page.url()).searchParams.get("workflow");
  expect(firstVersionId).not.toBeNull();
  expect(workflowId).not.toBeNull();
  await page.reload();
  await expect(page.getByText("Workflow v1")).toBeVisible();
  await expect(page.locator("article video")).toHaveCount(2);
  await expect(page.getByText("workflow-browser-gate-v1")).toBeAttached();

  await cards.nth(1).getByLabel("自然语言场景描述").fill(
    "展示红黄蓝三条 Lorenz 轨迹，并在明显分离时停顿两秒。",
  );
  await page.getByRole("button", { name: "保存新版本" }).click();
  await expect(page.getByText("已保存 Workflow v2。")).toBeVisible();
  await expect(page.locator("article video")).toHaveCount(1);
  const beforePartial = sceneRunRequests(requests).length;
  await page.getByRole("button", { name: "生成所有未完成 Preview" }).click();
  await expect(page.locator("article video")).toHaveCount(2);
  expect(sceneRunRequests(requests).length - beforePartial).toBe(1);

  const beforeReorder = sceneRunRequests(requests).length;
  await cards.nth(1).getByRole("button", { name: "上移场景" }).click();
  await expect(cards.nth(0).getByLabel("标题")).toHaveValue("吸引子轨迹");
  await page.getByRole("button", { name: "保存新版本" }).click();
  await expect(page.getByText("已保存 Workflow v3。")).toBeVisible();
  expect(sceneRunRequests(requests)).toHaveLength(beforeReorder);
  await page.getByRole("button", { name: "合成整片 Preview" }).click();
  await expect(page.getByText("workflow-browser-gate-v1")).toBeAttached();
  expect(sceneRunRequests(requests)).toHaveLength(beforeReorder);

  const currentVersionId = new URL(page.url()).searchParams.get("version");
  expect(currentVersionId).not.toBeNull();
  const secondContext = await browser.newContext();
  await assertOwnerBoundary(secondContext, workflowId!, currentVersionId!, initialPassword);

  const mutations = requests.filter((request) => (
    (request.method() === "POST" || request.method() === "PATCH")
    && !request.url().endsWith("/api/v1/auth/login")
  ));
  expect(mutations.length).toBeGreaterThan(0);
  for (const request of mutations) {
    expect(new URL(request.url()).origin).toBe("http://localhost:13000");
    expect(request.headers()["x-csrf-token"]).toBeTruthy();
    expect(request.headers()["authorization"]).toBeUndefined();
  }
  expect(pageErrors).toEqual([]);
  expect(failedApi).toEqual([]);
  await secondContext.close();
  await context.close();
});
