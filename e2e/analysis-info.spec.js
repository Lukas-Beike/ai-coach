const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

async function performanceFixture(page, changes, route = "performance") {
  await page.route("**/api/performance", async (request) => {
    const response = await request.fetch();
    const data = await response.json();
    Object.assign(data.performance, changes);
    await request.fulfill({ response, json: data });
  });
  await page.goto(`/#analysis/${route}`);
  await expect(page.locator("#appShell")).toBeVisible();
  await page.waitForFunction(() => state.loadedAreas.has("performance") && !state.loadPromise);
}

test("@responsive recovery uses independent scales, honest coverage and weekly distributions", async ({ page }) => {
  await performanceFixture(page, { personal_recovery: {
    as_of: "2026-10-02", sleep_target_hours: 8,
    baselines: [
      { metric: "sleep", source: "Garmin Connect", measurement: "sleepTimeSeconds", observed_at: "2026-10-01", nights: 1,
        history: [{ date: "2026-09-30", value: 7 }, { date: "2026-10-01", value: 11 }] },
      { metric: "hrv", source: "Garmin Connect", measurement: "lastNightAvg", observed_at: "2026-10-01", nights: 28,
        status: "ok", lower: 50, upper: 60, position: "within", history: [{ date: "2026-09-30", value: 52 }, { date: "2026-10-01", value: 58 }] },
      { metric: "resting_hr", source: "Intervals.icu", measurement: "restingHR", observed_at: "2026-10-01", nights: 1,
        status: "insufficient_data", reason: "Mindestens 14 frühere passende Nächte erforderlich.", history: [{ date: "2026-10-01", value: 48 }] },
    ],
  } }, "recovery");
  const root = page.locator("#personalRecovery");
  await expect(root.locator(".analysis-chart-card")).toHaveCount(1);
  await expect(root.locator(".analysis-subchart")).toHaveCount(3);
  await expect(root.locator("svg")).toHaveCount(3);
  await expect(root.locator(".analysis-secondary-axis, .analysis-extremum")).toHaveCount(0);
  const sleep = root.locator(".analysis-subchart").filter({ has: page.getByRole("heading", { name: "Schlafdauer", exact: true }) });
  await expect(sleep.getByRole("button", { name: "Schlafdauer", exact: true })).toBeVisible();
  await expect(sleep.locator(".recovery-sleep-bar")).toHaveCount(2);
  await expect(sleep.locator(".analysis-target-line")).toHaveCount(1);
  await expect(sleep).toContainText("2/5 Tage mit Messung");
  const hrv = root.locator(".analysis-subchart").filter({ has: page.getByRole("heading", { name: "HRV", exact: true }) });
  await expect(hrv.locator(".analysis-baseline-band")).toHaveCount(1);
  await expect(hrv.locator(".analysis-point-value")).toHaveCount(0);
  await expect(hrv).toContainText("Innerhalb deines üblichen Bereichs");
  await expect(root).toContainText("Mindestens 14 frühere passende Nächte erforderlich");
  await expect(root.locator(".analysis-value-tick").first()).toHaveText("0");
  await sleep.locator(".analysis-day-marker").last().focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".analysis-info-tooltip:popover-open")).toContainText("Schlafdauer: 11:00 h");
  await page.keyboard.press("Escape");
  await root.getByRole("button", { name: "8 Wochen", exact: true }).click();
  await expect(root.getByRole("heading", { name: "Erholung · Letzte 8 Wochen", exact: true })).toBeVisible();
  await expect(root.getByRole("button", { name: "Schlafdauer", exact: true })).toBeVisible();
  await expect(root).toContainText("2/54 Tage mit Messung");
  await expect(root.locator(".analysis-range-whisker")).toHaveCount(2);
  const weeklySleep = root.locator(".analysis-subchart").first();
  await weeklySleep.getByText("Werte ansehen", { exact: true }).click();
  await expect(weeklySleep.locator("tbody")).toContainText("2 Messungen · Streuung 8:00 h bis 10:00 h");
  await expect(weeklySleep).toContainText("01.10.2026");
  await expect(weeklySleep).not.toContainText("04.10.2026 · Garmin");
  expect((await new AxeBuilder({ page }).include("#personalRecovery").analyze()).violations).toEqual([]);
  expect(await root.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
});

test("@responsive load separates CTL and ATL from zero-centred TSB and preserves gaps", async ({ page }) => {
  const points = Array.from({ length: 8 }, (_, index) => ({ date: `2026-09-${String(index + 1).padStart(2, "0")}`, ctl: index === 4 ? null : 40 + index, atl: index === 4 ? null : 55 - index, tsb: index === 4 ? null : index * 3 - 15 }));
  await performanceFixture(page, { history: { start: "2026-09-01", end: "2026-09-08", load: { points }, metrics: {} } }, "load");
  const root = page.locator("#analysisLoadCharts");
  await expect(root).toBeVisible();
  await expect(page.locator("#analysisHistoryCharts")).toBeHidden();
  await expect(root.locator("svg")).toHaveCount(2);
  await expect(root.getByRole("button", { name: "CTL · Fitness", exact: true })).toBeVisible();
  await expect(root.getByRole("button", { name: "ATL · Ermüdung", exact: true })).toBeVisible();
  const form = root.locator(".analysis-subchart").last();
  await expect(form.locator(".analysis-zero-line")).toHaveCount(1);
  await expect(form.locator(".analysis-form-area")).toHaveCount(2);
  const ranges = await form.locator(".analysis-value-tick").allTextContents();
  expect(Number(ranges[0])).toBe(-Number(ranges.at(-1)));
  const path = await root.locator('path[data-series="0"]').first().getAttribute("d");
  expect(path.match(/M/g)).toHaveLength(2);
  const dates = await root.locator("svg").evaluateAll((charts) => charts.map((chart) => [...chart.querySelectorAll(".analysis-date-tick")].map((tick) => tick.textContent)));
  expect(dates[0]).toEqual(dates[1]);
  await root.locator(".analysis-day-marker").last().focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".analysis-info-tooltip:popover-open")).toContainText("TSB · Form: 6");
  await page.keyboard.press("Escape");
  await expect(root.locator(".is-selected")).toHaveCount(2);
  const overlay = form.locator(".analysis-plot-hit");
  const overlayBounds = await overlay.boundingBox();
  await overlay.click({ position: { x: overlayBounds.width * .95, y: overlayBounds.height / 2 } });
  await expect(page.locator(".analysis-info-tooltip:popover-open")).toContainText("TSB · Form: 0");
  await page.keyboard.press("Escape");
  expect((await new AxeBuilder({ page }).include("#analysisLoadCharts").analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("@responsive sparse performance shows measurements and sources without invented trends", async ({ page }) => {
  await performanceFixture(page, { history: {
    start: "2026-09-01", end: "2026-09-02", load: { points: [] },
    metrics: {
      cycling_ftp_watts: [{ source: "Garmin Connect", points: [{ date: "2026-09-01", value: 200 }, { date: "2026-09-02", value: 210 }] }],
      run_threshold_pace_seconds_per_km: [{ source: "Garmin Connect", points: [{ date: "2026-09-01", value: 300 }, { date: "2026-09-02", value: 290 }] }],
      running_vo2max_ml_kg_min: [{ source: "Garmin Connect", points: [{ date: "2026-09-02", value: 49 }] }],
    },
  } });
  const root = page.locator("#analysisHistoryCharts");
  await expect(root.locator(".analysis-chart-card")).toHaveCount(2);
  await expect(root.locator("svg")).toHaveCount(0);
  await expect(root.getByRole("button", { name: "Lauf · Schwellenpace", exact: true })).toBeVisible();
  await expect(root).toContainText("kein belastbarer Trend");
  await expect(root).toContainText("Seit 01.09.2026: −0:10 min/km");
  await expect(root).toContainText("02.09.2026 · Garmin Connect");
  const button = root.getByRole("button", { name: "Rad · FTP", exact: true });
  await button.click();
  const info = root.getByRole("tooltip").filter({ hasText: "Rad · FTP · Garmin Connect" });
  await expect(info).toBeVisible();
  await expect(button).toHaveAttribute("aria-expanded", "true");
  const bounds = await info.boundingBox();
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(page.viewportSize().width);
  await page.keyboard.press("Escape");
  await button.focus(); await page.keyboard.press("Enter"); await expect(info).toBeVisible();
  await page.keyboard.press("Escape");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("sparse FTP stays unconnected alongside a dense eFTP series", async ({ page }) => {
  await performanceFixture(page, { history: {
    start: "2026-09-01", end: "2026-09-03", load: { points: [] }, metrics: {
      cycling_ftp_watts: [{ source: "Garmin Connect", points: [{ date: "2026-09-01", value: 200 }, { date: "2026-09-02", value: 210 }] }],
      cycling_eftp_watts: [{ source: "Intervals.icu", points: [{ date: "2026-09-01", value: 205 }, { date: "2026-09-02", value: 208 }, { date: "2026-09-03", value: 212 }] }],
    },
  } });
  const chart = page.locator("#analysisHistoryCharts svg");
  await expect(chart).toHaveCount(1);
  await expect(chart.locator('circle[data-series="0"]')).toHaveCount(2);
  await expect(chart.locator('path[data-series="0"]')).toHaveCount(0);
  await expect(chart.locator('path[data-series="1"]')).toHaveCount(1);
  await expect(page.locator("#analysisHistoryCharts")).toContainText("Seit 01.09.2026: +10 W");
});

test("@responsive pace ticks stay distinct and faster pace is higher", async ({ page }) => {
  await performanceFixture(page, { history: { start: "2026-09-01", end: "2026-09-03", load: { points: [] }, metrics: {
    run_threshold_pace_seconds_per_km: [{ source: "Garmin Connect", points: [{ date: "2026-09-01", value: 300 }, { date: "2026-09-02", value: 295 }, { date: "2026-09-03", value: 290 }] }],
  } } });
  const chart = page.locator("#analysisHistoryCharts svg");
  await expect(chart).toHaveCount(1);
  const ticks = await chart.locator(".analysis-value-tick").allTextContents();
  expect(new Set(ticks).size).toBe(ticks.length);
  const y = await chart.locator("circle").evaluateAll((dots) => dots.map((dot) => Number(dot.getAttribute("cy"))));
  expect(y.at(-1)).toBeLessThan(y[0]);
  await expect(chart.locator(".analysis-extremum, .analysis-secondary-axis")).toHaveCount(0);
  const dates = await chart.locator(".analysis-date-tick").allTextContents();
  expect(new Set(dates).size).toBe(dates.length);
  const labelSizes = await chart.locator("text").evaluateAll((labels) => labels.map((label) => label.getBoundingClientRect().height));
  expect(Math.min(...labelSizes)).toBeGreaterThanOrEqual(11);
});

test("personal load bands use earlier known values and keep values and context in tooltips", async ({ page }) => {
  const points = Array.from({ length: 30 }, (_, index) => ({ date: `2026-09-${String(index + 1).padStart(2, "0")}`, ctl: 40 + index, atl: 50 + index, tsb: -10 }));
  points.at(-1).ctl = 500;
  await performanceFixture(page, { history: { start: "2026-09-01", end: "2026-09-30", load: { points }, metrics: {} } }, "load");
  const root = page.locator("#analysisLoadCharts");
  await expect(root.locator(".analysis-baseline-band")).toHaveCount(3);
  await expect(root).toContainText("Persönlicher üblicher Bereich: 47–61 · 29 frühere Tage");
  await root.getByRole("button", { name: "Aktuelle Woche", exact: true }).click();
  await expect(root.locator(".analysis-point-value")).toHaveCount(0);
  await expect(root.locator(".analysis-metric-meta").first()).toBeHidden();
  await root.getByRole("button", { name: "CTL · Fitness", exact: true }).click();
  await expect(root.locator(".analysis-info-tooltip:popover-open")).toContainText("500");
  await expect(root.locator(".analysis-info-tooltip:popover-open")).toContainText("29 frühere Tage");
  await expect(root.locator(".analysis-baseline-band")).toHaveCount(3);
});
