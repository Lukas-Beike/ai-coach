const { test, expect } = require("@playwright/test");

const routes = [
  ["plan/season", (page) => page.locator("#seasonPreparation .competition-card").first()],
  ["nutrition/diary", (page) => page.locator("#nutritionTotals .nutrition-total").first()],
  ["nutrition/week", (page) => page.locator("#nutritionWeek .nutrition-week-chart-day").first()],
  ["nutrition/products", (page) => page.locator("#nutritionProductsPanel")],
  ["analysis/load", (page) => page.locator("#sessionPerformance").getByRole("heading", { name: /^Trainingsfokus/ })],
  ["analysis/running", (page) => page.locator("#performancePredictions .race-predictions-table")],
  ["analysis/recovery", (page) => page.locator("#personalRecovery .analysis-chart-card").first()],
];

test("@responsive navigation and banners keep their text inside at 200 % text size", async ({ page }) => {
  await page.goto("/#coach");
  await page.waitForFunction(() => state.initialStateLoaded);
  // Banner content and measurement share one evaluate so a sync poll cannot hide a banner in between.
  const measure = () => page.evaluate(() => {
    document.documentElement.style.fontSize = "200%";
    const action = { href: "#more/connections", label: "Anbindungen öffnen" };
    updateStatusSources({
      offline: { level: "warning", title: "Offline", detail: "Änderungen können gerade nicht gespeichert werden.", stand: true },
      coach_error: { level: "critical", title: "Coach benötigt Aufmerksamkeit", detail: "Das OpenAI-Guthaben ist aufgebraucht. Bitte im OpenAI-Billing Guthaben hinzufügen." },
      provider: { level: "critical", title: "Anbindung benötigt Aufmerksamkeit", detail: "2 Anbindungen benötigen manuelles Eingreifen.", action },
      intervals_key: { level: "info", title: "Intervals.icu-API-Schlüssel fehlt", action, dismiss() {} },
    });
    document.querySelector("#statusStrip").dataset.expanded = "true";
    renderStatusStrip();
    const banners = [document.querySelector("#statusStrip")];
    const nav = [".bottom-nav", ".desktop-nav"].map((selector) => document.querySelector(selector)).filter((element) => element.getClientRects().length);
    const problems = nav.length === 1 ? [] : [`${nav.length} navigation bars visible`];
    for (const container of [...nav, ...banners]) {
      const box = container.getBoundingClientRect();
      if (!box.width) problems.push(`${container.id || container.className} not rendered`);
      if (box.left < 0 || box.right > document.documentElement.clientWidth + 1) problems.push(`${container.id || container.className} leaves the viewport`);
      for (const element of [container, ...container.querySelectorAll("*")]) {
        if (!element.getClientRects().length || element instanceof SVGElement) continue;
        // The low-screen strip cuts its one line with an ellipsis on purpose; the button opens the full text.
        if (getComputedStyle(element).textOverflow === "ellipsis") continue;
        // Inline labels report no scroll size, so their box must also stay inside the container.
        const inner = element.getBoundingClientRect();
        if (element.scrollWidth > element.clientWidth + 1 || inner.left < box.left - 1 || inner.right > box.right + 1) problems.push(`${container.id || container.className} > ${element.tagName.toLowerCase()}.${element.className} "${element.textContent.trim().slice(0, 30)}"`);
      }
    }
    return problems;
  });
  expect(await measure()).toEqual([]);
  // Phone projects also cover the 560-767 px band, where the bottom bar uses its larger label size.
  if (page.viewportSize().width < 560) {
    await page.setViewportSize({ width: 600, height: 900 });
    expect(await measure(), "600 px").toEqual([]);
  }
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
