const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

async function open(page, route, ready) {
  await page.goto(`/#${route}`);
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator(ready).first()).toBeVisible({ timeout: 30_000 });
}

// Interactive controls below 44 px on the route; chart bars (SVG) and controls inside closed details are excluded.
async function smallControls(page) {
  return page.evaluate(() => [...document.querySelectorAll("button, a[href], select, summary, input:not([type=hidden]):not([type=checkbox]):not([type=radio])")]
    .filter((element) => element.getClientRects().length && !(element instanceof SVGElement) && !element.closest("[hidden], [inert]"))
    .map((element) => ({ element, box: element.getBoundingClientRect() }))
    .filter(({ box }) => box.width < 43.5 || box.height < 43.5)
    .map(({ element, box }) => `${element.tagName.toLowerCase()}.${element.className} ${Math.round(box.width)}x${Math.round(box.height)} ${(element.getAttribute("aria-label") || element.textContent).trim().slice(0, 30)}`));
}

test.beforeEach(async ({ page }) => {
  expect((await page.request.get("/api/fixture/demo")).ok()).toBe(true);
  await page.addInitScript(() => { try { localStorage.setItem("intervals-coach-appearance", "light"); } catch { /* storage unavailable */ } });
});

test("@responsive light analysis load has no axe violation and no control below 44 px", async ({ page }) => {
  test.setTimeout(120_000);
  await open(page, "analysis/load", "#sessionPerformance h3");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  const focus = page.locator("#sessionPerformance");
  await expect(focus.locator(".training-focus-legend strong").first()).toHaveCSS("color", await focus.locator("h3").evaluate((node) => getComputedStyle(node).color));
  expect((await new AxeBuilder({ page }).include("#dataPanel").analyze()).violations).toEqual([]);
  expect(await smallControls(page)).toEqual([]);
  await page.goto("/#analysis/performance");
  await expect(page.locator("#performancePredictions .race-predictions-table")).toBeVisible({ timeout: 30_000 });
  expect(await smallControls(page)).toEqual([]);
});

test("@responsive derived values carry the chip and race predictions are whole minutes", async ({ page }) => {
  test.setTimeout(120_000);
  await open(page, "analysis/performance", "#performancePredictions .race-predictions-table");
  const predictions = page.locator("#performancePredictions");
  await expect(predictions.getByRole("heading", { name: /^Laufprognosen/ }).locator(".estimate-chip")).toHaveText("Schätzung");
  const times = await predictions.locator("tbody td").allTextContents();
  expect(times.length).toBeGreaterThan(0);
  for (const time of times) expect(time).toMatch(/^(\d{1,2} min|\d{1,2}:\d{2} h)$/);
  await open(page, "analysis/load", "#sessionPerformance h3");
  for (const title of [/^Session-RPE-Last/, /^Kurz-\/Langzeitbelastung/]) {
    await expect(page.getByRole("heading", { name: title }).first().locator(".estimate-chip")).toHaveText("Schätzung");
  }
  // A dashed series shows its dash in the legend.
  await expect(page.locator(".analysis-chart-legend li[data-line='dashed']").first()).toBeVisible();
});

test("@responsive nutrition diary shows calories as hero with one equal macro row", async ({ page }) => {
  await open(page, "nutrition/diary", "#nutritionTotals .nutrition-total");
  const tiles = page.locator("#nutritionTotals .nutrition-total");
  await expect(tiles).toHaveCount(6);
  await expect(tiles.first()).toHaveClass(/is-hero/);
  const boxes = await tiles.evaluateAll((nodes) => nodes.map((node) => {
    const box = node.getBoundingClientRect();
    const value = node.querySelector("strong").getBoundingClientRect();
    return { top: Math.round(box.top), height: Math.round(box.height), width: Math.round(box.width), valueHeight: Math.round(value.height) };
  }));
  expect(boxes[1].top).toBe(boxes[2].top);
  expect(boxes[2].top).toBe(boxes[3].top);
  expect(boxes[1].height).toBe(boxes[2].height);
  expect(boxes[2].height).toBe(boxes[3].height);
  expect(boxes[0].width).toBeGreaterThan(boxes[1].width * 2);
  // One line per value: the unit does not wrap below the number.
  expect(boxes[0].valueHeight).toBeLessThan(60);
  await expect(tiles.first().locator(".nutrition-unit")).toHaveText("kcal");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("@responsive nutrition history collapses days without data and products keep one primary action", async ({ page }) => {
  await open(page, "nutrition/week", "#nutritionWeek .nutrition-week-chart-day");
  const empty = page.locator("#nutritionWeek .nutrition-week-chart-day.is-empty");
  await expect(empty.first()).toContainText("keine Daten");
  const heights = await page.locator("#nutritionWeek .nutrition-week-chart-day").evaluateAll((nodes) => nodes.map((node) => [node.classList.contains("is-empty"), node.getBoundingClientRect().height]));
  const emptyHeight = Math.max(...heights.filter(([isEmpty]) => isEmpty).map(([, height]) => height));
  const fullHeight = Math.min(...heights.filter(([isEmpty]) => !isEmpty).map(([, height]) => height));
  expect(emptyHeight).toBeLessThan(fullHeight / 1.5);
  expect(await smallControls(page)).toEqual([]);
  await open(page, "nutrition/products", "#nutritionBarcodeButton");
  const actions = page.locator(".nutrition-tools > .nutrition-actions");
  await expect(actions.locator(".push-button")).toHaveCount(1);
  const widths = await actions.locator("button").evaluateAll((nodes) => nodes.map((node) => Math.round(node.getBoundingClientRect().width)));
  expect(widths[1]).toBe(widths[2]);
  expect(widths[0]).toBeGreaterThan(widths[1]);
  await expect(page.getByText("Nährwerttabelle auswählen", { exact: true })).toHaveCount(0);
});

test("@responsive desktop uses a readable text size, two charts per row and a grouped rail", async ({ page }) => {
  test.skip(!(page.viewportSize().width >= 1100), "Desktop layout");
  await open(page, "analysis/load", "#sessionPerformance h3");
  const metrics = await page.evaluate(() => {
    const cards = [...document.querySelectorAll("#analysisLoadCharts > .analysis-chart-card")];
    const noteSize = parseFloat(getComputedStyle(document.querySelector(".analysis-chart-card .analysis-chart-note, .analysis-chart-card p, .analysis-chart-card summary")).fontSize);
    const chartText = parseFloat(getComputedStyle(document.querySelector(".analysis-chart-card > svg text")).fontSize) * (document.querySelector(".analysis-chart-card > svg").getBoundingClientRect().width / document.querySelector(".analysis-chart-card > svg").viewBox.baseVal.width);
    const rail = [...document.querySelectorAll(".desktop-nav .nav-item")].map((item) => Math.round(item.getBoundingClientRect().top));
    return { firstRow: cards.slice(0, 2).map((card) => Math.round(card.getBoundingClientRect().top)), noteSize, chartText, rail };
  });
  expect(metrics.firstRow[0]).toBe(metrics.firstRow[1]);
  expect(metrics.noteSize).toBeGreaterThanOrEqual(14.5);
  expect(metrics.chartText).toBeGreaterThanOrEqual(11);
  expect(metrics.rail.at(-1) - metrics.rail.at(-2)).toBeLessThan(80);
  await open(page, "more/profile", "#profileForm");
  const { widest, limit } = await page.evaluate(() => ({
    widest: Math.max(...[...document.querySelectorAll("#profileForm .profile-section[open] > label")].map((node) => node.getBoundingClientRect().width)),
    limit: 40 * parseFloat(getComputedStyle(document.documentElement).fontSize),
  }));
  expect(widest).toBeLessThanOrEqual(limit + 1);
});
