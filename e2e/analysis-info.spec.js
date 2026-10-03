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
  const charts = page.locator("#personalRecovery .analysis-chart-card");
  await expect(charts).toHaveCount(2);
  await expect(charts.first().locator("h3")).toHaveText("Erholung \u00b7 Aktuelle Woche");
  await expect(charts.first().locator(".recovery-sleep-bar")).toHaveCount(2);
  await expect(charts.first().locator(".recovery-sleep-line")).toHaveCount(1);
  expect(await charts.first().locator(".recovery-sleep-line").evaluate((line) => Number.parseFloat(getComputedStyle(line).strokeWidth))).toBe(1);
  await expect(charts.first().locator(".recovery-sleep-axis").first()).toContainText("3 h");
  await expect(charts.first().locator(".recovery-sleep-axis").last()).toContainText("10 h");
  await expect(charts.first().locator(".analysis-point-value")).toHaveCount(0);
  await expect(charts.first().locator(".analysis-chart-legend")).not.toContainText("%");
  await charts.first().locator(".analysis-day-marker").last().focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".analysis-info-tooltip:popover-open")).toContainText("Schlafdauer: 8 h");
  await page.keyboard.press("Escape");
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
    ] }],
      run_threshold_pace_seconds_per_km: [{ source: "Garmin Connect", points: [
        { date: "2026-09-01", value: 300 }, { date: "2026-09-02", value: 290 },
      ] }],
      cycling_vo2max_ml_kg_min: [{ source: "Garmin Connect", points: [{ date: "2026-09-01", value: 50 }, { date: "2026-09-02", value: 51 }] }],
      running_vo2max_ml_kg_min: [{ source: "Garmin Connect", points: [{ date: "2026-09-01", value: 48 }, { date: "2026-09-02", value: 49 }] }],
    },
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
  await expect(charts.locator(".analysis-chart-card")).toHaveCount(3);
  const runningChart = charts.locator(".analysis-chart-card").filter({ has: page.getByRole("heading", { name: "Leistungsentwicklung · Laufen", exact: true }) });
  const cyclingChart = charts.locator(".analysis-chart-card").filter({ has: page.getByRole("heading", { name: "Leistungsentwicklung · Rad", exact: true }) });
  await expect(runningChart.getByRole("button", { name: /Schwellenpace: 4:50/ })).toBeVisible();
  await expect(cyclingChart.getByRole("button", { name: /FTP: 210 W/ })).toBeVisible();
  await expect(runningChart.locator(".analysis-chart-legend")).not.toContainText("%");
  await expect(cyclingChart.locator(".analysis-chart-legend")).not.toContainText("%");
  await expect(runningChart.locator(".analysis-secondary-axis")).toHaveCount(2);
  await expect(cyclingChart.locator(".analysis-secondary-axis")).toHaveCount(3);
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
  await expect(tooltip).not.toContainText("Basis");
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


test("@responsive chart dates, values and focus labels follow their data", async ({ page }) => {
  await page.goto("/#analysis/performance");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.waitForFunction(() => state.loadedAreas.has("performance") && !state.loadPromise);
  await page.evaluate(() => {
    const points = Array.from({ length: 8 }, (_, index) => ({ date: addDateKey("2026-09-01", index * 7), value: 30 + index }));
    document.querySelector("#analysisHistoryCharts").replaceChildren(analysisChart("Test", [{ label: "Fitness", points }], "", "2026-09-01", "2026-10-20", "", true));
    renderTrainingFocus({ start: "2026-09-01", end: "2026-10-20", classified_sessions: 3, categories: { low_aerobic: { load: 60 }, high_aerobic: { load: 30 }, anaerobic: { load: 10 } } });
  });
  const chart = page.locator("#analysisHistoryCharts svg");
  expect(await chart.locator(".analysis-date-tick").count()).toBeGreaterThan(2);
  await expect(chart.locator(".analysis-point-value")).toHaveCount(0);
  await expect(chart.locator(".analysis-extremum-label")).toHaveCount(2);
  await expect(chart.locator(".analysis-extremum-label").first()).toHaveText("30");
  await expect(chart.locator(".analysis-extremum-label").last()).toHaveText("37");
  const point = chart.locator(".analysis-day-marker").last();
  await point.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".analysis-info-tooltip:popover-open")).toContainText("Fitness: 37");
  await page.keyboard.press("Escape");
  expect((await chart.boundingBox()).height).toBeLessThanOrEqual(201);
  const alignment = await page.evaluate(() => {
    const parts = [...document.querySelectorAll(".training-focus-share span")];
    return [...document.querySelectorAll(".training-focus-legend li")].map((item, index) => {
      const a = item.getBoundingClientRect(), b = parts[index].getBoundingClientRect();
      return Math.abs(a.x + a.width / 2 - b.x - b.width / 2);
    });
  });
  expect(Math.max(...alignment)).toBeLessThan(2);
  const percentage = page.locator(".training-focus-legend strong").last();
  expect((await percentage.boundingBox()).height).toBeLessThan(30);
});


test("@responsive coinciding extrema stay readable and day details retain original values", async ({ page }) => {
  await page.goto("/#analysis/performance");
  await page.waitForFunction(() => state.loadedAreas.has("performance") && !state.loadPromise);
  await page.evaluate(() => {
    const series = Array.from({length: 5}, (_, index) => ({ label: `Reihe ${index}`, color: index, unit: "W", points: [
      {date: "2026-09-01", value: 0, actual: 200}, {date: "2026-09-02", value: 5, actual: 210},
    ] }));
    document.querySelector("#analysisHistoryCharts").replaceChildren(analysisChart("Vergleich", series, "%", "2026-09-01", "2026-09-02", "", true));
  });
  const chart = page.locator("#analysisHistoryCharts svg");
  const boxes = await chart.locator(".analysis-extremum-background").evaluateAll((items) => items.map((item) => {
    const box = item.getBoundingClientRect(); return {left:box.left,right:box.right,top:box.top,bottom:box.bottom};
  }));
  expect(boxes.length).toBe(10);
  for (let i=0; i<boxes.length; i++) for (let j=i+1; j<boxes.length; j++) {
    const a=boxes[i], b=boxes[j];
    expect(a.right <= b.left || a.left >= b.right || a.bottom <= b.top || a.top >= b.bottom).toBe(true);
  }
  await chart.locator(".analysis-day-marker").last().focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".analysis-info-tooltip:popover-open")).toContainText("210 W (5 %)");
});
