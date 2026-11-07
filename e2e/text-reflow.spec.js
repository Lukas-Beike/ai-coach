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

test("@responsive navigation and banners keep their text inside at 200 % text size", async ({ page }) => {
  await page.goto("/#coach");
  await page.waitForFunction(() => state.initialStateLoaded);
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "200%";
    const show = (selector, update) => {
      const element = document.querySelector(selector);
      update(element);
      element.hidden = false;
    };
    show("#statusCard", (card) => {
      card.hidden = false;
      card.querySelector("#statusTitle").textContent = "Das OpenAI-Guthaben ist aufgebraucht";
      card.querySelector("#statusDetail").textContent = "Bitte im OpenAI-Billing Guthaben hinzufügen.";
    });
    show("#connectivityNotice", (notice) => { notice.textContent = "Offline – Änderungen können gerade nicht gespeichert werden."; });
    show("#providerAttentionBanner", () => { document.querySelector("#providerAttentionDetail").textContent = "2 Anbindungen benötigen manuelles Eingreifen."; });
    show("#setupBanner", () => { document.querySelector("#setupBannerDetail").textContent = "Garmin Connect und Intervals.icu fehlen"; });
  });
  const overflow = await page.evaluate(() => {
    const containers = [".bottom-nav", ".desktop-nav", "#statusCard", "#connectivityNotice", "#providerAttentionBanner", "#setupBanner"]
      .map((selector) => document.querySelector(selector))
      .filter((element) => element && element.getClientRects().length);
    const problems = [];
    for (const container of containers) {
      const box = container.getBoundingClientRect();
      if (box.left < 0 || box.right > document.documentElement.clientWidth + 1) problems.push(`${container.className || container.id} leaves the viewport`);
      for (const element of [container, ...container.querySelectorAll("*")]) {
        // Skip SVG and visually hidden accessible names (1 px clip boxes).
        if (!element.getClientRects().length || element instanceof SVGElement || element.clientWidth <= 1) continue;
        if (element.scrollWidth > element.clientWidth + 1) problems.push(`${container.id || container.className} > ${element.tagName.toLowerCase()}.${element.className} "${element.textContent.trim().slice(0, 30)}"`);
      }
    }
    return problems;
  });
  expect(overflow).toEqual([]);
});

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
