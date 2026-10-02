const { test, expect } = require("@playwright/test");

test("@responsive recovery exposes partial measured history without counting future days", async ({ page }) => {
  const report = {
    as_of: "2026-10-02",
    baselines: [{ metric: "sleep", source: "Garmin Connect", measurement: "sleepTimeSeconds",
      observed_at: "2026-10-01", nights: 1, history: [
        { date: "2026-09-30", value: 7 }, { date: "2026-10-01", value: 8 },
      ] }],
  };
  await page.route("**/api/performance", async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    data.performance.personal_recovery = report;
    await route.fulfill({ response, json: data });
  });
  await page.goto("/#analysis/recovery");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.waitForFunction(() => state.data?.performance?.personal_recovery?.baselines?.length === 1);
  await page.evaluate(async () => {
    await applyNavigationRoute("analysis/recovery", { historyMode: "replace" });
  });
  const charts = page.locator("#personalRecovery .analysis-chart-card");
  await expect(charts).toHaveCount(2);
  await charts.first().getByText("Datenabdeckung", { exact: true }).click();
  await expect(charts.first().locator(".analysis-coverage")).toContainText("2/5 Tage mit Messung");
  await charts.last().getByText("Datenabdeckung", { exact: true }).click();
  await expect(charts.last().locator(".analysis-coverage")).toContainText("2/54 Tage mit Messung");
  await expect(charts.last().locator(".analysis-coverage")).toContainText("42-Tage-Normalbereich: 1 frühere Messnächte");
  await expect(charts.last().locator(".analysis-coverage")).toContainText("keine Nullwerte oder bestätigten Ruhetage");
  expect(await page.locator("#personalRecovery").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  report.baselines = [];
  await page.evaluate(() => renderPersonalRecovery({ as_of: "2026-10-02", baselines: [] }));
  await page.locator("#personalRecovery .analysis-chart-card").last().getByText("Datenabdeckung", { exact: true }).click();
  await expect(page.locator("#personalRecovery .analysis-chart-card").last()).toContainText("Keine Messhistorie vorhanden.");
});

test("@responsive performance legend opens source information on demand", async ({ page }) => {
  const history = {
    start: "2026-09-01", end: "2026-09-02",
    load: { points: [{ date: "2026-09-01", ctl: 30, atl: 35, tsb: -5 }] },
    metrics: { cycling_ftp_watts: [{ source: "Garmin Connect", points: [
      { date: "2026-09-01", value: 200 }, { date: "2026-09-02", value: 210 },
    ] }] },
  };
  await page.route("**/api/performance", async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    data.performance.history = history;
    await route.fulfill({ response, json: data });
  });
  await page.goto("/#analysis/performance");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.waitForFunction(() => Boolean(state.data?.performance?.history));
  await page.evaluate(async () => {
    await applyNavigationRoute("analysis/performance", { historyMode: "replace" });
  });
  const charts = page.locator("#analysisHistoryCharts");
  await expect(charts.locator(".analysis-chart-note")).toHaveCount(0);
  const loadLegend = charts.locator(".analysis-chart-legend").first();
  await expect(loadLegend).not.toContainText(/CTL|ATL|TSB/);
  await expect(loadLegend.getByRole("button", { name: /^Fitness:/ })).toBeVisible();
  expect(await loadLegend.evaluate((element) => getComputedStyle(element).display)).toBe("flex");
  if (page.viewportSize().width >= 600) {
    const rows = await loadLegend.locator("li").evaluateAll((items) => items.map((item) => Math.round(item.getBoundingClientRect().top)));
    expect(new Set(rows).size).toBe(1);
  }
  const legend = charts.getByRole("button", { name: /Rad · FTP: 210 W/ });
  await expect(legend).toBeVisible();
  await expect(legend).not.toContainText("Garmin");
  await legend.click();
  const tooltip = charts.getByRole("tooltip").filter({ hasText: "Rad · FTP · Garmin Connect" });
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toContainText("02.09.2026");
  await expect(tooltip).toContainText("Basis 01.09.2026");
  await expect(legend).toHaveAttribute("aria-expanded", "true");
  const bounds = await tooltip.boundingBox();
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(page.viewportSize().width);
  await page.keyboard.press("Escape");
  await expect(tooltip).toBeHidden();
  await page.evaluate(() => renderSyncStatus({ running: false, message: null }));
  await legend.focus();
  await page.keyboard.press("Enter");
  await expect(tooltip).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(tooltip).toBeHidden();
  await page.evaluate(() => renderAnalysisHistory({ start: "2026-09-01", end: "2026-09-02", load: { points: [] }, metrics: {} }));
  await expect(charts.locator(".analysis-chart-note")).toHaveCount(0);
});
