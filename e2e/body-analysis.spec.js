const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

function bodyHistory() {
  const start = "2026-07-15";
  const dates = Array.from({ length: 84 }, (_, index) => new Date(Date.parse(`${start}T12:00:00Z`) + index * 86400000).toISOString().slice(0, 10));
  const make = (source, metric, transform) => ({ source, unit: metric === "weight_kg" ? "kg" : metric === "body_fat_pct" ? "%" : "W/kg",
    ...(metric === "cycling_w_per_kg" ? { power_method: source === "Garmin Connect" ? "FTP" : "eFTP" } : {}),
    points: dates.map((date, index) => {
      const missingWeek = index >= 35 && index <= 41;
      const value = missingWeek || (metric === "body_fat_pct" && source === "Intervals.icu Wellness") ? null : transform(index);
      if (value == null) return { date, value: null };
      const point = { date, value: Math.round(value * 1000) / 1000, observed_at: date, synced_at: `${source} sync` };
      if (metric === "cycling_w_per_kg") Object.assign(point, {
        ftp_watts: 280 + index, ftp_observed_at: date, ftp_synced_at: `${source} FTP sync`,
        weight_kg: 70, weight_observed_at: dates[Math.max(0, index - 1)], weight_synced_at: "Garmin weight sync",
        weight_source: "Garmin Connect", weight_age_days: 1,
      });
      return point;
    }),
  });
  const metrics = {
    weight_kg: [make("Intervals.icu Wellness", "weight_kg", (index) => 70 + index / 100), make("Garmin Connect", "weight_kg", (index) => 71 + index / 100)],
    body_fat_pct: [make("Intervals.icu Wellness", "body_fat_pct", () => 18), make("Garmin Connect", "body_fat_pct", (index) => 19 + index / 100)],
    cycling_w_per_kg: [make("Garmin Connect", "cycling_w_per_kg", (index) => (280 + index) / 70), make("Intervals.icu", "cycling_w_per_kg", (index) => (270 + index) / 71)],
  };
  const end = dates.at(-1);
  return { start, end, load: { points: [] }, metrics: {}, body: { version: 1, default_window: "12w", windows: {
    "14d": { start: dates.at(-14), end, days: 14, metrics: Object.fromEntries(Object.entries(metrics).map(([key, values]) => [key, values.map((item) => ({ ...item, points: item.points.slice(-14) }))])) },
    "12w": { start, end, days: 84, metrics },
  } } };
}

test("@responsive Body plots measurements and W/kg retains provenance inside cycling development", async ({ page }) => {
  if (test.info().project.name === "mobile-small") expect(page.viewportSize().width).toBe(320);
  await page.route("**/api/performance", async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    data.performance.history = bodyHistory();
    await route.fulfill({ response, json: data });
  });
  await page.goto("/#analysis/body");
  await expect(page.locator("#appShell")).toBeVisible();
  const root = page.locator("#bodyAnalysisCharts");
  await expect(root).toBeVisible();
  await expect(root.locator("[data-body-metric]")).toHaveCount(2);
  await expect(root.locator("[data-body-metric='weight_kg'] svg")).toHaveCount(1);
  const overview = root.locator("[data-body-overview]");
  await expect(overview.locator("tbody tr")).toHaveCount(2);
  await expect(overview.locator("[data-metric='weight_kg'] td")).toHaveText("71,8 kg");
  await expect(overview.locator("[data-metric='body_fat_pct'] td")).toHaveText("19,8 %");
  await expect(overview.locator("th small")).toHaveText(["06.10.2026", "06.10.2026"]);
  expect(await overview.evaluate((element) => element.closest("section").parentElement.firstElementChild.contains(element))).toBe(true);
  await expect(root).not.toContainText("Intervals.icu");
  await expect(root).not.toContainText("Garmin");
  const missing = root.locator("[data-body-metric='weight_kg']");
  await expect(missing.locator("circle[data-series='0']")).toHaveCount(11);
  await root.getByRole("button", { name: "Letzte 14 Tage", exact: true }).click();
  await expect(root.locator("[data-body-metric='weight_kg'] circle[data-series='0']")).toHaveCount(14);
  await expect(root.locator("[data-body-metric='body_fat_pct'] circle[data-series='0']")).toHaveCount(14);
  await expect(root.locator("circle[data-series='1']")).toHaveCount(0);
  await expect(overview.locator("[data-metric='weight_kg'] td")).toHaveText("71,8 kg");
  await page.evaluate(() => {
    const body = structuredClone(state.data.performance.history.body);
    for (const window of Object.values(body.windows)) {
      for (const metric of ["weight_kg", "body_fat_pct"]) {
        window.metrics[metric] = window.metrics[metric].filter((item) => item.source !== "Garmin Connect");
      }
    }
    renderBodyAnalysis(body);
  });
  await expect(overview.locator("td")).toHaveText(["—", "—"]);
  await expect(root.locator("circle[data-series]")).toHaveCount(0);
  expect(await new AxeBuilder({ page }).include("#bodyAnalysisCharts").analyze()).toEqual(expect.objectContaining({ violations: [] }));
  await expect(root.locator("[data-body-metric='cycling_w_per_kg']")).toHaveCount(0);
  await page.evaluate(() => { location.hash = "#analysis/performance"; });
  const weightRoot = page.locator("#analysisHistoryCharts [data-analysis-section='development-Rad']");
  await expect(weightRoot).toBeVisible();
  await expect(root).toBeHidden();
  const details = weightRoot.locator("[data-body-metric='cycling_w_per_kg']");
  await details.locator(".analysis-day-marker[data-date='2026-10-06']").focus();
  await page.keyboard.press("Enter");
  await expect(details.locator(".analysis-info-tooltip:popover-open")).toContainText("FTP 06.10.2026");
  await expect(details.locator(".analysis-info-tooltip:popover-open")).toContainText("eFTP 06.10.2026");
  await expect(details.locator(".analysis-info-tooltip:popover-open")).toContainText("Gewicht 05.10.2026 (Garmin Connect)");
  await page.keyboard.press("Escape");
  await expect(details.locator("circle[data-series='0']")).toHaveCount(11);
  expect((await new AxeBuilder({ page }).include("#analysisHistoryCharts").analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
