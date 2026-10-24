const { test, expect } = require("@playwright/test");

const routes = [
  ["plan/season", (page) => page.locator("#seasonPreparation .competition-card").first()],
  ["nutrition/diary", (page) => page.locator("#nutritionTotals .nutrition-total").first()],
  ["nutrition/week", (page) => page.locator("#nutritionWeek .nutrition-week-chart-day").first()],
  ["nutrition/products", (page) => page.locator("#nutritionProductsPanel")],
  ["analysis/load", (page) => page.locator("#sessionPerformance").getByRole("heading", { name: /^Trainingsfokus/ })],
  ["analysis/performance", (page) => page.locator("#performancePredictions .race-predictions-table")],
  ["analysis/recovery", (page) => page.locator("#personalRecovery .analysis-chart-card").first()],
  ["analysis/sessions", (page) => page.locator("#activityAnalysis")],
];

test("@responsive pages do not scroll horizontally at 200 % text size", async ({ page, request }) => {
  test.setTimeout(180_000);
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  expect((await request.get("/api/fixture/features")).ok()).toBeTruthy();
  await page.goto("/#coach");
  await page.waitForFunction(() => state.initialStateLoaded);
  await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
  for (const [route, ready] of routes) {
    await page.evaluate((target) => AppRouter.navigate(target, { historyMode: "replace" }), route);
    await expect(ready(page), route).toBeVisible();
    if (route === "nutrition/week") await page.locator("#nutritionWeek").getByText("Tageswerte anzeigen", { exact: true }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), route).toBeLessThanOrEqual(0);
  }
});
