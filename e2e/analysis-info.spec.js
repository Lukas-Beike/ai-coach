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

test("@responsive recovery uses independent scales, honest coverage over exactly fourteen days", async ({ page }) => {
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
  const hrv = root.locator(".analysis-subchart").filter({ has: page.getByRole("heading", { name: "HRV", exact: true }) });
  await expect(hrv).toContainText("Innerhalb deines üblichen Bereichs");
  await expect(root).toContainText("Mindestens 14 frühere passende Nächte erforderlich");
  await sleep.locator(".analysis-day-marker").last().focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".analysis-info-tooltip:popover-open")).toContainText("Schlafdauer: 11:00 h");
  await page.keyboard.press("Escape");
  await expect(root.getByRole("heading", { name: "Erholung · Letzte 14 Tage", exact: true })).toBeVisible();
  await expect(root.locator(".analysis-period-controls")).toHaveCount(1);
  await expect(root.locator("svg > title").first()).toHaveText("Schlafdauer · 19.09.2026 bis 02.10.2026");
  await sleep.getByText("Werte ansehen", { exact: true }).click();
  await expect(sleep.locator("tbody tr")).toHaveCount(2);
  await expect(sleep.locator("tbody")).toContainText("01.10.2026");
  expect((await new AxeBuilder({ page }).include("#personalRecovery").analyze()).violations).toEqual([]);
  expect(await root.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
});

test("@responsive Garmin acute load switches fourteen days and twelve weeks with real gaps", async ({ page }) => {
  const points = Array.from({ length: 90 }, (_, index) => ({ date: new Date(Date.UTC(2026, 6, 3 + index)).toISOString().slice(0, 10), value: index >= 38 && index <= 44 ? null : 300 + index }));
  await performanceFixture(page, { history: { start: points[0].date, end: points.at(-1).date, load: { source: "Garmin Connect", points }, metrics: {} } }, "load");
  const root = page.locator("#analysisLoadCharts");
  await expect(root.locator("svg")).toHaveCount(1);
  await expect(root.locator("circle[data-series='0']")).toHaveCount(11);
  await expect(root.locator("path[data-series='0']")).toHaveAttribute("d", /M.*M/);
  await expect(root).not.toContainText("Fitness");
  await root.getByRole("button", { name: "Letzte 14 Tage", exact: true }).click();
  await expect(root.locator("circle[data-series='0']")).toHaveCount(14);
  await root.locator(".analysis-day-marker").last().focus();
  await page.keyboard.press("Enter");
  await expect(root.locator(".analysis-info-tooltip:popover-open")).toContainText("389");
  await expect(root.locator(".analysis-info-tooltip:popover-open")).toContainText("Garmin Connect");
  await page.keyboard.press("Escape");
  await root.getByRole("button", { name: "12 Wochen", exact: true }).click();
  await expect(root.locator("circle[data-series='0']")).toHaveCount(11);
  expect((await new AxeBuilder({ page }).include("#analysisLoadCharts").analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("@responsive sparse performance shows measurements and the current value line", async ({ page }) => {
  await performanceFixture(page, { history: {
    start: "2026-09-01", end: "2026-09-08", load: { points: [] },
    metrics: {
      cycling_ftp_watts: [{ source: "Garmin Connect", points: [{ date: "2026-09-01", value: 200 }, { date: "2026-09-08", value: 210 }] }],
      run_threshold_pace_seconds_per_km: [{ source: "Garmin Connect", points: [{ date: "2026-09-01", value: 300 }, { date: "2026-09-08", value: 290 }] }],
      running_vo2max_ml_kg_min: [{ source: "Garmin Connect", points: [{ date: "2026-09-08", value: 49 }] }],
    },
  } });
  const root = page.locator("#analysisHistoryCharts");
  await expect(root.locator(".analysis-chart-card")).toHaveCount(2);
  await expect(root.locator("svg")).toHaveCount(3);
  await expect(root.locator(".analysis-current-line")).toHaveCount(3);
  expect(await root.locator(".analysis-point-value").allTextContents()).toEqual(expect.arrayContaining(["4:50", "49", "210"]));
  await expect(root).toContainText("kein belastbarer Trend");
  await expect(root).toContainText("08.09.2026 · Garmin Connect");
  const button = root.getByRole("button", { name: "FTP", exact: true });
  await button.click();
  const info = root.getByRole("tooltip").filter({ hasText: "FTP · Garmin Connect" });
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

test("sparse FTP uses a current value line alongside a dense eFTP series", async ({ page }) => {
  await performanceFixture(page, { history: {
    start: "2026-09-01", end: "2026-09-15", load: { points: [] }, metrics: {
      cycling_ftp_watts: [{ source: "Garmin Connect", points: [{ date: "2026-09-01", value: 200 }, { date: "2026-09-08", value: 210 }] }],
      cycling_eftp_watts: [{ source: "Intervals.icu", points: [{ date: "2026-09-01", value: 205 }, { date: "2026-09-08", value: 208 }, { date: "2026-09-15", value: 212 }] }],
    },
  } });
  const chart = page.locator("#analysisHistoryCharts svg");
  await expect(chart).toHaveCount(1);
  await expect(chart.locator('circle[data-series="0"]')).toHaveCount(2);
  await expect(chart.locator('path[data-series="0"]')).toHaveCount(0);
  await expect(chart.locator('.analysis-current-line[data-series="0"]')).toHaveCount(1);
  await expect(chart.locator('path[data-series="1"]')).toHaveCount(1);
  await expect(page.locator("#analysisHistoryCharts")).toContainText("Seit 01.09.2026: +10 W");
});

test("@responsive pace ticks stay distinct and faster pace is higher", async ({ page }) => {
  await performanceFixture(page, { history: { start: "2026-09-01", end: "2026-09-15", load: { points: [] }, metrics: {
    run_threshold_pace_seconds_per_km: [{ source: "Garmin Connect", points: [{ date: "2026-09-01", value: 300 }, { date: "2026-09-08", value: 295 }, { date: "2026-09-15", value: 290 }] }],
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
  const labelSizes = await chart.locator("text").evaluateAll((labels) => labels.map((label) => Math.round(label.getBoundingClientRect().height * 1000) / 1000));
  expect(Math.min(...labelSizes)).toBeGreaterThanOrEqual(11);
});

test("@responsive repeated performance values are labelled once without a normal range", async ({ page }) => {
  const points = Array.from({ length: 30 }, (_, index) => ({ date: `2026-09-${String(index + 1).padStart(2, "0")}`, value: index % 2 ? 210 : 200 }));
  await performanceFixture(page, { history: { start: "2026-09-01", end: "2026-09-30", load: { points: [] }, metrics: {
    cycling_ftp_watts: [{ source: "Garmin Connect", points }],
  } } });
  const root = page.locator("#analysisHistoryCharts");
  await expect(root.locator(".analysis-period-controls")).toHaveCount(0);
  expect((await root.locator(".analysis-point-value").allTextContents()).sort()).toEqual(["200", "210"]);
  await expect(root.locator('circle[data-series="0"]')).toHaveCount(5);
  await expect(root.locator(".analysis-current-line")).toHaveCount(1);
  await expect(root.locator(".analysis-baseline-band")).toHaveCount(0);
  await root.getByRole("button", { name: "FTP", exact: true }).click();
  await expect(root.locator(".analysis-info-tooltip:popover-open")).not.toContainText("Grüner Bereich");
  await page.keyboard.press("Escape");
});

test("@responsive performance uses weekly last values and medians, keeps equal weeks and ignores the load period", async ({ page }) => {
  const points = [
    { date: "2026-06-01", value: 999 },
    { date: "2026-09-01", value: 200 }, { date: "2026-09-02", value: 220 }, { date: "2026-09-03", value: 210 },
    { date: "2026-09-08", value: 220 }, { date: "2026-09-09", value: 210 },
  ];
  await performanceFixture(page, { history: { start: "2026-08-01", end: "2026-09-30", load: { points: [] }, metrics: {
    cycling_ftp_watts: [{ source: "Garmin Connect", points }],
    cycling_eftp_watts: [{ source: "Intervals.icu", points }],
    run_threshold_pace_seconds_per_km: [{ source: "Garmin Connect", points: points.slice(1).map((point) => ({ ...point, value: 500 - point.value })) }],
  } } });
  const root = page.locator("#analysisHistoryCharts");
  await expect(root.locator(".analysis-period-controls")).toHaveCount(0);
  const ftp = root.locator(".analysis-subchart").filter({ has: page.getByRole("heading", { name: "Leistungsschwelle · FTP / eFTP", exact: true }) });
  await ftp.getByText("Werte ansehen", { exact: true }).click();
  await expect(ftp.locator("tbody tr")).toHaveCount(2);
  await expect(ftp.locator("tbody")).toContainText("03.09.2026");
  await expect(ftp.locator("tbody")).toContainText("09.09.2026");
  await expect(ftp.locator("tbody td:nth-child(2)")).toHaveText([/210 W/, /210 W/]);
  await expect(ftp.locator("tbody td:nth-child(3)")).toHaveText([/210 W.*3 Messungen/, /215 W.*2 Messungen/]);
  const pace = root.locator(".analysis-subchart").filter({ has: page.getByRole("heading", { name: "Schwellenpace", exact: true }) });
  await pace.getByText("Werte ansehen", { exact: true }).click();
  await expect(pace.locator("tbody td:nth-child(2)")).toHaveText([/4:50 min\/km/, /4:50 min\/km/]);
  await page.evaluate(async () => { await applyNavigationRoute("analysis/load", { historyMode: "replace" }); });
  await page.locator("#analysisLoadCharts").getByRole("button", { name: "Letzte 14 Tage", exact: true }).click();
  await page.evaluate(async () => { await applyNavigationRoute("analysis/performance", { historyMode: "replace" }); });
  await expect(ftp.locator("tbody tr")).toHaveCount(2);
  await expect(root.locator("svg > title").first()).toContainText("13.07.2026 bis 30.09.2026");
});

test("@responsive latest measurement stays visible without inventing measurements in empty weeks", async ({ page }) => {
  await performanceFixture(page, { history: { start: "2026-09-01", end: "2026-09-30", load: { points: [] }, metrics: {
    running_vo2max_ml_kg_min: [{ source: "Garmin Connect", points: [{ date: "2026-09-20", value: 49 }] }],
  } } });
  const root = page.locator("#analysisHistoryCharts");
  await expect(root.locator(".analysis-period-controls")).toHaveCount(0);
  await expect(root.locator("svg")).toHaveCount(1);
  await expect(root.locator(".analysis-current-line")).toHaveCount(1);
  await expect(root.locator(".analysis-point-value")).toHaveText(["49"]);
  await expect(root.locator("circle")).toHaveCount(1);
  await root.locator(".analysis-day-marker").last().focus();
  await page.keyboard.press("Enter");
  await expect(root.locator(".analysis-info-tooltip:popover-open")).toContainText("20.09.2026");
  await expect(root.locator(".analysis-info-tooltip:popover-open")).toContainText("1 Messungen");
  await page.keyboard.press("Escape");
  await root.getByText("Werte ansehen", { exact: true }).click();
  await expect(root.locator("tbody tr")).toHaveCount(1);
});

test("sleep uses an average line without a normal range or target", async ({ page }) => {
  const history = Array.from({ length: 30 }, (_, index) => ({ date: `2026-09-${String(index + 1).padStart(2, "0")}`, value: index % 2 ? 8 : 7 }));
  await performanceFixture(page, { personal_recovery: { as_of: "2026-09-30", sleep_target_hours: 8,
    baselines: [{ metric: "sleep", source: "Garmin Connect", measurement: "sleepTimeSeconds", observed_at: "2026-09-30", nights: 29,
      status: "ok", lower: 7, upper: 8, history }],
  } }, "recovery");
  const root = page.locator("#personalRecovery");
  await expect(root.locator(".analysis-baseline-band")).toHaveCount(0);
  await expect(root.locator(".analysis-target-line")).toHaveCount(0);
  await expect(root.locator(".analysis-average-line")).toHaveCount(1);
  await expect(root.locator(".analysis-average-value")).toHaveText("Ø 7:30 h");
  await expect(root.locator("svg").first()).toContainText("7:00");
  await expect(root.locator("svg").first()).toContainText("8:00");
  await root.getByRole("button", { name: "Schlafdauer", exact: true }).click();
  const info = root.locator(".analysis-info-tooltip:popover-open");
  await expect(info).toContainText("Durchschnitt");
  await expect(info).not.toContainText("Grüner Bereich");
  await expect(info).not.toContainText("persönliches Schlafziel");
});

test("stale recovery history cannot bypass a rejected backend baseline", async ({ page }) => {
  const history = Array.from({ length: 30 }, (_, index) => ({ date: `2026-09-${String(index + 1).padStart(2, "0")}`, value: 50 + index % 3 }));
  await performanceFixture(page, { personal_recovery: { as_of: "2026-10-02",
    baselines: [{ metric: "hrv", source: "Garmin Connect", measurement: "lastNightAvg", observed_at: "2026-09-30", nights: 29,
      status: "insufficient_data", reason: "Messung veraltet.", history }],
  } }, "recovery");
  const root = page.locator("#personalRecovery");
  await expect(root.locator(".analysis-baseline-band")).toHaveCount(0);
  await root.getByRole("button", { name: "HRV", exact: true }).click();
  await expect(root.locator(".analysis-info-tooltip:popover-open")).toContainText("Messung veraltet.");
  await expect(root.locator(".analysis-info-tooltip:popover-open")).not.toContainText("Grüner Bereich");
});

test("@responsive dense performance retains every measured week without overlapping labels", async ({ page }) => {
  const points = Array.from({ length: 12 }, (_, index) => ({ date: new Date(Date.UTC(2026, 6, 13 + index * 7)).toISOString().slice(0, 10), value: 47.6 + index * .15 }));
  await performanceFixture(page, { history: { start: "2026-07-13", end: "2026-09-30", load: { points: [] }, metrics: {
    running_vo2max_ml_kg_min: [{ source: "Garmin Connect", points }],
    cycling_ftp_watts: [{ source: "Garmin Connect", points: points.map((point, index) => ({ ...point, value: 266 + index })) }],
    cycling_eftp_watts: [{ source: "Intervals.icu", points: points.map((point, index) => ({ ...point, value: 268 + index })) }],
  } } });
  const charts = page.locator("#analysisHistoryCharts svg");
  const geometry = await charts.evaluateAll((charts) => charts.map((chart) => {
    const labels = [...chart.querySelectorAll(".analysis-point-value")].map((label) => {
      const box = label.getBoundingClientRect();
      return { left: box.left, right: box.right, top: box.top, bottom: box.bottom };
    });
    return { count: chart.querySelectorAll("circle[data-series]").length, labels,
      overlap: labels.some((a, index) => labels.slice(index + 1).some((b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top)) };
  }));
  expect(geometry.map((chart) => chart.count)).toEqual([12, 24]);
  for (const chart of geometry) expect(chart.overlap).toBe(false);
  await page.locator("#analysisHistoryCharts details").first().locator("summary").click();
  await expect(page.locator("#analysisHistoryCharts details").first().locator("tbody tr")).toHaveCount(12);
});

test("@responsive performance keeps predictions in the dedicated table", async ({ page }) => {
  await performanceFixture(page, { available: true, metrics: {
    cycling_ftp_watts: { value: 280, unit: "W" }, running_vo2max_ml_kg_min: { value: 52 },
    weight_kg: { value: 72, unit: "kg", source: "Garmin Connect" },
    run_5k_seconds: { value: 1200, unit: "s", source: "Garmin Connect Laufprognose" },
  } });
  await expect(page.locator("#performancePredictions")).toContainText("Laufprognosen");
  await expect(page.locator("#performancePredictions")).toContainText("20:00");
  await expect(page.locator("#performanceSummary")).toBeHidden();
});
