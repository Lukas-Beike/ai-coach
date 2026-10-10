const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

async function performanceFixture(page, changes, route = "performance") {
  await page.route("**/api/performance", async (request) => {
    const response = await request.fetch();
    const data = await response.json();
    Object.assign(data.performance, { metrics: {} }, changes);
    await request.fulfill({ response, json: data });
  });
  await page.goto(`/#analysis/${route}`);
  await expect(page.locator("#appShell")).toBeVisible();
  await page.waitForFunction(() => state.loadedAreas.has("performance") && !state.loadPromise);
}

test("@responsive standard demo shows one compact race table and sport-specific collapsible development", async ({ page }) => {
  expect((await page.request.get("/api/fixture/demo")).ok()).toBe(true);
  await page.goto("/#analysis/performance");
  const table = page.locator("#performancePredictions");
  await expect(table.locator("tbody tr")).toHaveCount(4);
  await expect(table.locator("thead th")).toHaveCount(2);
  for (const distance of ["5 km", "10 km", "Halbmarathon", "Marathon"]) await expect(table.getByRole("rowheader", { name: distance, exact: true })).toBeVisible();
  await expect(table).not.toContainText("Garmin");
  await expect(page.locator("[data-race-distance], #existingPerformanceReports")).toHaveCount(0);
  await expect(page.locator("#analysisHistoryCharts")).not.toContainText("Historische Entwicklung");
  const cycling = page.locator("[data-analysis-section='development-Rad']");
  const running = page.locator("[data-analysis-section='development-Lauf']");
  const powerProfile = cycling.locator("#cyclingPowerProfile");
  await expect(powerProfile.locator("tbody tr")).toHaveCount(5);
  await expect(powerProfile.locator("tbody td")).toHaveText(Array.from({ length: 10 }, () => /^\d+(?:,\d+)? W$/));
  await expect(cycling.locator("[data-body-metric='cycling_w_per_kg']")).toHaveCount(1);
  await expect(running).toContainText("Lauf-Belastbarkeit");
  await expect(running.locator("#performancePredictions")).toHaveCount(1);
  await expect(running.locator(".analysis-group-title")).toHaveText("Laufen");
  await expect(cycling.locator(".analysis-group-title")).toHaveText("Rad");
  const endurance = page.locator("#performanceEnduranceCharts");
  await expect(endurance).toContainText("Ausdauer-Score");
  expect(await endurance.evaluate((element) => element.previousElementSibling.id)).toBe("currentPerformance");
  for (const group of [running, cycling]) {
    const title = await group.locator(".analysis-group-title").boundingBox();
    const help = await group.locator("xpath=../button[contains(@class, 'analysis-section-help')]").boundingBox();
    expect(help.x - title.x - title.width).toBeGreaterThanOrEqual(12);
    expect(help.width).toBeGreaterThanOrEqual(44);
    expect(help.height).toBeGreaterThanOrEqual(44);
    await group.locator("xpath=../button[contains(@class, 'analysis-section-help')]").click();
    await expect(group).toHaveAttribute("open", "");
    await page.keyboard.press("Escape");
  }
  await running.locator(":scope > summary").click();
  await expect(table).toBeHidden();
  await running.locator(":scope > summary").click();
  await expect(page.locator("#performanceWeightCharts")).toHaveCount(0);
  await cycling.locator(":scope > summary").click();
  await expect(cycling).not.toHaveAttribute("open", "");
  await expect(cycling.locator("svg").first()).toBeHidden();
  await expect(running.locator("svg").first()).toBeVisible();
  await cycling.locator(":scope > summary").focus();
  await page.keyboard.press("Enter");
  await expect(cycling.locator("svg").first()).toBeVisible();
  await page.evaluate(() => renderAnalysisHistory(state.data.performance.history));
  await expect(cycling.locator("svg").first()).toBeVisible();
  await cycling.locator(":scope > summary").click();
  await page.evaluate(() => renderAnalysisHistory(state.data.performance.history));
  await expect(cycling.locator("svg").first()).toBeHidden();
  await cycling.locator(":scope > summary").click();
  expect((await new AxeBuilder({ page }).include("#dataPanel").analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("@responsive current performance groups real values by sport before the charts", async ({ page }) => {
  await performanceFixture(page, { metrics: {
    cycling_ftp_watts: { value: 280, unit: "W", source: "Garmin Connect", observed_at: "2026-10-01", freshness: "stale" },
    run_threshold_pace_seconds_per_km: { value: 270, unit: "s/km", source: "Garmin Connect" },
    running_vo2max_ml_kg_min: { value: 52, unit: "ml/kg/min", source: "Intervals.icu" },
    run_5k_seconds: { value: 1200, unit: "s", source: "Garmin Connect" },
  } });
  const root = page.locator("#currentPerformance");
  await expect(root).toBeVisible();
  await expect(root.locator("caption")).toHaveText(["Laufen", "Radfahren"]);
  await expect(root.locator("[data-metric='cycling_ftp_watts']")).toContainText("280 W");
  await expect(root.locator("small")).toHaveCount(0);
  await expect(root).not.toContainText("Garmin");
  await expect(root).not.toContainText("Intervals.icu");
  await expect(root).not.toContainText("01.10.2026");
  await expect(root.locator("[data-metric='run_threshold_pace_seconds_per_km']")).toContainText("4:30");
  await expect(root.locator("[data-metric='run_threshold_watts'] td")).toHaveText("\u2014");
  await expect(root).not.toContainText("5 km");
  expect(await root.evaluate((element) => !!(element.compareDocumentPosition(document.getElementById("analysisHistoryCharts")) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
  expect((await new AxeBuilder({ page }).include("#currentPerformance").analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => { location.hash = "#analysis/load"; });
  await expect(root).toBeHidden();
});

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
  await expect(root.locator("svg")).toHaveCount(2);
  await expect(root.locator(".analysis-secondary-axis, .analysis-extremum")).toHaveCount(0);
  await expect(root.getByRole("heading", { name: /^Erholung · Letzte 14 Tage/ })).toBeVisible();
  await expect(root.getByRole("button", { name: "Erholung · Letzte 14 Tage: Informationen", exact: true })).toBeVisible();
  await expect(root.locator(".analysis-period-controls")).toHaveCount(1);
  expect((await new AxeBuilder({ page }).include("#personalRecovery").analyze()).violations).toEqual([]);
  expect(await root.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
});

test("@responsive Garmin acute load switches fourteen days and twelve weeks with real gaps", async ({ page }) => {
  const points = Array.from({ length: 90 }, (_, index) => ({ date: new Date(Date.UTC(2026, 6, 3 + index)).toISOString().slice(0, 10), value: index >= 38 && index <= 44 ? null : 300 + index }));
  await performanceFixture(page, { history: { start: points[0].date, end: points.at(-1).date, load: { source: "Garmin Connect", points }, training_time: { source: "Intervals.icu", points: points.map((point) => ({ ...point, value: point.value == null ? null : 1 })) }, metrics: {} } }, "load");
  const loadRoot = page.locator("#analysisLoadCharts");
  await expect(loadRoot.locator("svg")).toHaveCount(2);
  const root = loadRoot.locator(".analysis-chart-card").first();
  await expect(root.locator("circle[data-series='0']")).toHaveCount(11);
  await expect(root.locator("rect.analysis-series-bar")).toHaveCount(11);
  await expect(root.locator(".analysis-point-value[data-value-series]")).toHaveCount(11);
  expect(await root.locator(".analysis-date-tick").allTextContents()).toEqual(expect.arrayContaining([expect.stringMatching(/^\d{2}\.\d{2}$/)]));
  await expect(root).not.toContainText("KW ");
  await expect(root.locator("path[data-series='0']")).toHaveAttribute("d", /M.*L/);
  await expect(root).not.toContainText("Fitness");
  await loadRoot.getByRole("button", { name: "Letzte 14 Tage", exact: true }).click();
  await expect(root.locator("circle[data-series='0']")).toHaveCount(14);
  for (const chart of await loadRoot.locator(".analysis-chart-card").all()) {
    await expect(chart.locator(".analysis-point-value[data-value-series]")).toHaveCount(14);
    const boxes = await chart.locator(".analysis-point-value[data-value-series]").evaluateAll((labels) => labels.map((label) => {
      const box = label.getBoundingClientRect(); return { left: box.left, right: box.right, top: box.top, bottom: box.bottom };
    }));
    for (let index = 0; index < boxes.length; index++) {
      const box = boxes[index];
      expect(boxes.slice(index + 1).some((other) => box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top)).toBe(false);
    }
  }
  await loadRoot.getByRole("button", { name: "12 Wochen", exact: true }).click();
  await expect(root.locator("circle[data-series='0']")).toHaveCount(11);
  for (const svg of await loadRoot.locator("svg").all()) {
    const geometry = await svg.evaluate((element) => {
      const dots = [...element.querySelectorAll("circle[data-series]")];
      const bars = [...element.querySelectorAll("rect.analysis-series-bar")];
      const path = element.querySelector("path[data-series]").getAttribute("d");
      return { dots: dots.map((dot) => [Number(dot.getAttribute("cx")), Number(dot.getAttribute("cy"))]),
        bars: bars.map((bar) => [Number(bar.getAttribute("x")) + Number(bar.getAttribute("width")) / 2, Number(bar.getAttribute("y"))]),
        line: [...path.matchAll(/[ML](-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/g)].map((match) => [Number(match[1]), Number(match[2])]) };
    });
    expect(geometry.dots.length).toBeGreaterThan(0);
    expect(geometry.bars.length).toBe(geometry.dots.length);
    geometry.dots.forEach((dot, index) => {
      expect(geometry.bars[index][0]).toBeCloseTo(dot[0], 4);
      expect(geometry.bars[index][1]).toBeCloseTo(dot[1], 4);
      expect(geometry.line[index][0]).toBeCloseTo(dot[0], 2);
      expect(geometry.line[index][1]).toBeCloseTo(dot[1], 2);
    });
  }
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
  await expect(root.locator("svg")).toHaveCount(2);
  await expect(root.locator(".analysis-current-line")).toHaveCount(0);
  await expect(root.locator("path[data-series]")).toHaveCount(2);
  expect(await root.locator(".analysis-point-value").allTextContents()).toEqual(expect.arrayContaining(["4:50", "210"]));
  await expect(root).toContainText("08.09.2026 · Garmin Connect");
  const button = root.getByRole("button", { name: "Erklärung zu FTP", exact: true });
  await button.click();
  const info = root.getByRole("tooltip").filter({ hasText: "FTP · Garmin Connect" });
  await expect(info).toBeVisible();
  await expect(button).toHaveAttribute("aria-expanded", "true");
  const bounds = await info.boundingBox();
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(page.viewportSize().width);
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
  await expect(chart.locator('path[data-series="0"]')).toHaveCount(1);
  await expect(chart.locator('.analysis-current-line[data-series="0"]')).toHaveCount(0);
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
  await expect(root.locator(".analysis-current-line")).toHaveCount(0);
  await expect(root.locator(".analysis-baseline-band")).toHaveCount(0);
  await root.getByRole("button", { name: "Erklärung zu FTP", exact: true }).click();
  await expect(root.locator(".analysis-info-tooltip:popover-open")).not.toContainText("Grüner Bereich");
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
  await page.evaluate(async () => { await AppRouter.navigate("analysis/load", { historyMode: "replace" }); });
  await page.locator("#analysisLoadCharts").getByRole("button", { name: "Letzte 14 Tage", exact: true }).click();
  await page.evaluate(async () => { await AppRouter.navigate("analysis/performance", { historyMode: "replace" }); });
  await expect(ftp.locator("tbody tr")).toHaveCount(2);
});

test("@responsive latest measurement stays visible without inventing measurements in empty weeks", async ({ page }) => {
  await performanceFixture(page, { history: { start: "2026-09-01", end: "2026-09-30", load: { points: [] }, metrics: {
    running_vo2max_ml_kg_min: [{ source: "Garmin Connect", points: [{ date: "2026-09-20", value: 49 }] }],
  } } });
  const root = page.locator("#analysisHistoryCharts");
  await expect(root.locator(".analysis-period-controls")).toHaveCount(0);
  await expect(root.locator("svg")).toHaveCount(0);
  await expect(root.locator(".analysis-current-line")).toHaveCount(0);
  await expect(root.locator(".analysis-point-value")).toHaveCount(0);
  await expect(root).toContainText("Ein einzelner Messwert zeigt noch keinen Verlauf");
  const values = root.locator(".analysis-subchart").filter({ hasText: "49" }).first().locator("details");
  await values.locator("summary").click();
  await expect(values.locator("tbody tr")).toHaveCount(1);
});

test("@responsive stale current value cannot float above the connected history line", async ({ page }) => {
  await performanceFixture(page, { history: { start: "2026-09-01", end: "2026-09-15", load: { points: [] }, metrics: {
    running_vo2max_ml_kg_min: [{ source: "Garmin Connect", points: [
      { date: "2026-09-01", value: 53 }, { date: "2026-09-02", value: 53 },
      { date: "2026-09-08", value: 53 }, { date: "2026-09-09", value: 53 }, { date: "2026-09-10", value: 53.5 },
    ] }],
  } } });
  const chart = page.locator("#analysisHistoryCharts svg");
  await expect(chart.locator(".analysis-current-line")).toHaveCount(0);
  const geometry = await chart.evaluate((svg) => {
    const path = svg.querySelector("path[data-series='0']").getAttribute("d");
    const line = [...path.matchAll(/[ML](-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/g)]
      .map((match) => [Number(match[1]).toFixed(2), Number(match[2]).toFixed(2)]);
    const markers = [...svg.querySelectorAll("circle[data-series='0']")]
      .map((circle) => [Number(circle.getAttribute("cx")).toFixed(2), Number(circle.getAttribute("cy")).toFixed(2)]);
    return { line, markers };
  });
  expect(geometry.line).toEqual(geometry.markers);
  await expect(chart).not.toContainText("53.5");
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
  const vo2max = page.locator("#analysisHistoryCharts .analysis-subchart").filter({ has: page.getByRole("heading", { name: "VO₂max · Schätzung", exact: true }) }).filter({ has: page.locator("circle[data-series='0']") }).first();
  await vo2max.locator("details summary").click();
  await expect(vo2max.locator("tbody tr")).toHaveCount(12);
});

test("@responsive performance keeps predictions in the dedicated table", async ({ page }) => {
  await performanceFixture(page, { available: true, metrics: {
    cycling_ftp_watts: { value: 280, unit: "W" }, running_vo2max_ml_kg_min: { value: 52 },
    weight_kg: { value: 72, unit: "kg", source: "Garmin Connect" },
    run_5k_seconds: { value: 1200, unit: "s", source: "Garmin Connect", note: "Garmin Connect Laufprognose" },
  } });
  await expect(page.locator("#performancePredictions")).toContainText("Laufprognosen");
  await expect(page.locator("#performancePredictions")).toContainText("20:00");
  await expect(page.locator("#performanceSummary")).toBeHidden();
});

test("@responsive historical race estimates never create duplicate charts", async ({ page }) => {
  await performanceFixture(page, {
    metrics: { run_5k_seconds: { value: 1200, unit: "s", source: "Garmin Connect", note: "Garmin Connect Laufprognose" } },
    history: { start: "2026-09-01", end: "2026-10-01", load: { points: [] }, metrics: {
      run_5k_seconds: [{ source: "Garmin Connect", points: [{ date: "2026-09-01", value: 1250 }, { date: "2026-09-15", value: 1200 }] }],
    } },
  });
  await expect(page.locator("#performancePredictions")).toContainText("20:00");
  await expect(page.locator("#performancePredictions")).not.toContainText("Garmin");
  await expect(page.locator("#analysisHistoryCharts svg")).toHaveCount(0);
  await expect(page.locator("[data-race-distance]")).toHaveCount(0);
});

test("@responsive provider metrics render as charts without raw text", async ({ page }) => {
  await performanceFixture(page, {
    history: {
      start: "2026-09-01", end: "2026-10-01", load: { points: [] }, metrics: {},
      provider_metrics: {
        endurance_score: { source: "Garmin Connect", aggregation: "weekly", unit: "unknown", status: "stale", points: [{ date: "2026-09-28", values: { enduranceScore: 712 } }] },
        running_tolerance: { source: "Garmin Connect", aggregation: "weekly", unit: "unknown", status: "failed", points: [] },
      },
    },
    personal_recovery: {
      as_of: "2026-10-01", sleep_target_hours: null, baselines: [], sleep_deficits: [],
      regularity: {
        method: "sleep-regularity-v1", timezone: "Europe/Berlin", status: "provisional", series: [{
          source: "Garmin Connect", method: "sleepStartTimestampGMT/sleepEndTimestampGMT", status: "provisional",
          coverage: { baseline_nights: 3, required_nights: 14 },
          points_14: [{ date: "2026-10-01", onset_at: "2026-09-30T22:15:00+02:00", wake_at: "2026-10-01T06:45:00+02:00", duration_hours: 8.5, onset_deviation_minutes: 15, wake_deviation_minutes: -10 }, { date: "2026-09-30" }],
          points_84: [],
        }],
      },
    },
  });
  const performance = page.locator("#analysisHistoryCharts");
  await expect(page.locator("#performanceEnduranceCharts").getByRole("heading", { name: "Ausdauer-Score" })).toBeVisible();
  await expect(performance.getByRole("heading", { name: "Lauf-Belastbarkeit" })).toHaveCount(0);
  await expect(performance).not.toContainText("Garmin-Provider-Metriken");
  await expect(performance).not.toContainText("Rohfeld");
  await page.evaluate(async () => { await AppRouter.navigate("analysis/recovery", { historyMode: "replace" }); });
  const recovery = page.locator("#personalRecovery");
  await expect(recovery).not.toContainText("Schlafdefizit");
  await expect(recovery).not.toContainText("Schlafregelm");
  await expect(page.locator("#analysisTagImpact, #analysisComparisons")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("@responsive predictions list only race estimates and never body weight", async ({ page }) => {
  await performanceFixture(page, { metrics: {
    weight_kg: { value: 72.4, unit: "kg", source: "Garmin Connect" },
    run_10k_seconds: { value: 2500, unit: "s", source: "Garmin Connect", note: "Garmin Connect Laufprognose" },
  } });
  const predictions = page.locator("#performancePredictions");
  await expect(predictions.getByRole("heading", { name: "Laufprognosen" })).toBeVisible();
  await expect(predictions.locator("tbody tr")).toHaveCount(1);
  await expect(predictions).toContainText("10 km");
  await expect(predictions).not.toContainText("Garmin Connect");
  await expect(predictions).not.toContainText("Gewicht");
  await expect(predictions).not.toContainText("72");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("@responsive missing race predictions explain the reason instead of an empty block", async ({ page }) => {
  await performanceFixture(page, { metrics: {
    weight_kg: { value: 72.4, unit: "kg", source: "Garmin Connect" },
  } });
  const predictions = page.locator("#performancePredictions");
  await expect(predictions).toBeVisible();
  await expect(predictions.getByRole("heading", { name: "Laufprognosen" })).toBeVisible();
  await expect(predictions).toContainText("Noch keine Prognosen – dafür fehlen aktuelle Leistungswerte aus Intervals.icu oder Garmin.");
  await expect(predictions.locator("table")).toHaveCount(0);
  await expect(predictions).not.toContainText("Gewicht");
});

test("@responsive legend info buttons have a 44px layout box, a German name and popovers inside the viewport", async ({ page }) => {
  await performanceFixture(page, { history: {
    start: "2026-09-01", end: "2026-09-08", load: { points: [] },
    metrics: { cycling_ftp_watts: [{ source: "Garmin Connect", points: [{ date: "2026-09-01", value: 200 }, { date: "2026-09-08", value: 210 }] }] },
  } });
  const root = page.locator("#analysisHistoryCharts");
  const button = root.getByRole("button", { name: "Erklärung zu FTP", exact: true });
  await expect(button).toHaveAttribute("aria-expanded", "false");
  await button.evaluate((element) => element.scrollIntoView({ block: "center", inline: "center" }));
  const box = await button.boundingBox();
  expect(box.width).toBeGreaterThanOrEqual(44);
  expect(box.height).toBeGreaterThanOrEqual(44);
  const center = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  const hits = await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.closest(".analysis-legend-info")?.getAttribute("aria-label") ?? null, { x: center.x + 20, y: center.y });
  expect(hits).toBe("Erklärung zu FTP");
  await button.click();
  const info = root.getByRole("tooltip").filter({ hasText: "FTP · Garmin Connect" });
  await expect(info).toBeVisible();
  await expect(button).toHaveAttribute("aria-expanded", "true");
  const viewport = page.viewportSize();
  const bounds = await info.boundingBox();
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.y).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(viewport.width);
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(viewport.height);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("@responsive legend info buttons are at least 44x44 and never overlap each other", async ({ page }) => {
  await performanceFixture(page, { history: {
    start: "2026-09-01", end: "2026-09-08", load: { points: [] },
    metrics: {
      cycling_ftp_watts: [{ source: "Garmin Connect", points: [{ date: "2026-09-01", value: 200 }, { date: "2026-09-08", value: 210 }] }],
      // The FTP chart shows its legend; FTP and eFTP give two neighbouring info buttons.
      cycling_eftp_watts: [{ source: "Intervals.icu", points: [{ date: "2026-09-01", value: 205 }, { date: "2026-09-08", value: 212 }] }],
    },
  } });
  const buttons = page.locator("#analysisHistoryCharts .analysis-chart-legend .analysis-legend-info");
  const count = await buttons.count();
  expect(count).toBeGreaterThanOrEqual(2);
  const boxes = [];
  for (let index = 0; index < count; index += 1) {
    const box = await buttons.nth(index).boundingBox();
    expect(box.width).toBeGreaterThanOrEqual(44);
    expect(box.height).toBeGreaterThanOrEqual(44);
    boxes.push(box);
  }
  for (let first = 0; first < boxes.length; first += 1) {
    for (let second = first + 1; second < boxes.length; second += 1) {
      const a = boxes[first], b = boxes[second];
      const overlaps = a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
      expect(overlaps, `legend buttons ${first} and ${second} overlap`).toBe(false);
    }
  }
});
