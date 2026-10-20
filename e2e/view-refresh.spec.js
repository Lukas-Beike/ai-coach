const { test, expect } = require("@playwright/test");

test("@responsive view refresh targets its active area and ignores stale views", async ({ page }) => {
  const posts = [];
  const broadRefreshes = [];
  let releaseRefresh;
  let holdNutritionRefresh = false;
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (request.method() === "POST" && (url.pathname.startsWith("/api/sync") || url.pathname === "/api/nutrition/sync")) broadRefreshes.push(url.pathname);
  });
  await page.route("**/api/analysis/refresh", async (route) => {
    posts.push({ path: "/api/analysis/refresh", body: route.request().postDataJSON() });
    await route.fulfill({ json: { status: "complete" } });
  });
  await page.route("**/api/nutrition/refresh", async (route) => {
    posts.push({ path: "/api/nutrition/refresh", body: route.request().postDataJSON() });
    if (holdNutritionRefresh) await new Promise((resolve) => { releaseRefresh = resolve; });
    await route.fulfill({ json: { status: "partial" } });
  });

  await page.goto("/#analysis/load");
  await expect(page.locator("#appShell")).toBeVisible();
  const analysisRefresh = page.locator("#analysisRefreshButton");
  await expect(analysisRefresh).toHaveAttribute("aria-label", "Analyse aktualisieren: Belastung");
  const analysisBox = await analysisRefresh.boundingBox();
  expect(analysisBox.width).toBeGreaterThanOrEqual(44);
  expect(analysisBox.height).toBeGreaterThanOrEqual(44);
  await analysisRefresh.click();
  await expect(page.locator("#analysisRefreshStatus")).toHaveText("Aktualisiert.");

  await page.evaluate(() => AppRouter.navigate("nutrition/diary", { historyMode: "none" }));
  await page.locator("#nutritionDate").fill("2026-10-19");
  await page.locator("#nutritionDate").dispatchEvent("change");
  const nutritionRefresh = page.locator("#nutritionRefreshButton");
  await expect(nutritionRefresh).toHaveAttribute("aria-label", "Ernährung aktualisieren: Tagebuch");
  await nutritionRefresh.click();
  await expect(page.locator("#nutritionRefreshStatus")).toHaveText("Teilweise aktualisiert.");

  await page.evaluate(() => AppRouter.navigate("nutrition/week", { historyMode: "none" }));
  await page.getByRole("button", { name: "12 Wochen", exact: true }).click();
  await expect(nutritionRefresh).toHaveAttribute("aria-label", "Ernährung aktualisieren: Verlauf, 12 Wochen");
  holdNutritionRefresh = true;
  releaseRefresh = null;
  await nutritionRefresh.click();
  await expect.poll(() => typeof releaseRefresh).toBe("function");
  expect(posts.filter((post) => post.path === "/api/nutrition/refresh")).toHaveLength(2);
  await page.getByRole("button", { name: "Letzte 14 Tage", exact: true }).click();
  releaseRefresh();
  await expect(nutritionRefresh).toBeEnabled();
  await expect(page.locator("#nutritionRefreshStatus")).toBeEmpty();

  holdNutritionRefresh = true;
  releaseRefresh = null;
  await nutritionRefresh.click();
  await expect.poll(() => typeof releaseRefresh).toBe("function");
  expect(posts.filter((post) => post.path === "/api/nutrition/refresh")).toHaveLength(3);
  await page.evaluate(() => AppRouter.navigate("analysis/performance", { historyMode: "none" }));
  releaseRefresh();
  await expect(nutritionRefresh).toBeEnabled();
  await expect(page.locator("#dataPanel")).toHaveClass(/active/);
  await expect(page.locator("#nutritionRefreshStatus")).toBeEmpty();

  expect(posts).toEqual([
    { path: "/api/analysis/refresh", body: { area: "load", days: 84 } },
    { path: "/api/nutrition/refresh", body: { area: "diary", date: "2026-10-19" } },
    { path: "/api/nutrition/refresh", body: { area: "week", days: 84 } },
    { path: "/api/nutrition/refresh", body: { area: "week", days: 14 } },
  ]);
  expect(broadRefreshes).toEqual([]);
});
