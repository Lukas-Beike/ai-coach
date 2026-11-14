const { test, expect } = require("@playwright/test");

test("@responsive performance keeps Garmin measurements and one cycling best per duration", async ({ page, request }) => {
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  await page.route("**/api/analysis/power-profiles", (route) => route.fulfill({ json: { all_time: { power: [
    { sport: "Ride", duration_seconds: 5, watts: 650, status: "ok", date: "2026-10-01" },
    { sport: "VirtualRide", duration_seconds: 5, watts: 700, status: "ok", date: "2026-10-02" },
    { sport: "Ride", duration_seconds: 60, watts: 420, status: "ok", date: "2026-10-01" },
  ], cache_coverage: { records: 20, unknown_records: 5, power_records: 14, power_unknown_records: 3 } }, critical_power: { window_days: 28, scope: "Experimentelle Modellschätzung", fits: [
    { sport: "ride", environment: "outdoor", status: "ok", cp_watts: 250, w_prime_joules: 18000, efforts: [{ effort_context: "race" }, { effort_context: "training" }] },
    { sport: "ride", environment: "indoor", status: "insufficient_data" },
    { sport: "run", environment: "outdoor", status: "ok", cs_mps: 4.12, d_prime_meters: 200 },
  ] } } }));
  await page.goto("/#analysis/cycling");
  await expect(page.locator("#currentPerformance")).toBeVisible();
  await page.waitForFunction(() => !!state.data?.performance?.history?.body);
  await page.evaluate(() => {
    const history = structuredClone(state.data.performance.history);
    history.end = "2026-10-04";
    history.preferred_providers = { cycling_ftp_watts: "garmin" };
    history.body.preferred_providers = { cycling_w_per_kg: "garmin" };
    history.metrics.cycling_ftp_watts = [{ source: "Garmin Connect", source_provider: "garmin", points: [
      { date: "2026-10-01", value: 270 }, { date: "2026-10-02", value: 272 }, { date: "2026-10-03", value: 275 },
    ] }];
    history.body.windows["12w"].metrics.cycling_w_per_kg = [
      { source: "Garmin Connect", source_provider: "garmin", points: [{ date: "2026-10-03", value: 3.8 }] },
    ];
    state.data.performance = { ...state.data.performance, history, metrics: {
      ...state.data.performance.metrics,
      running_max_hr_bpm: { value: 187, unit: "bpm", source_provider: "garmin" }, cycling_max_hr_bpm: { value: 200, unit: "bpm", source_provider: "intervals" },
      max_hr_bpm: { value: 187, unit: "bpm", source_provider: "garmin" },
      run_threshold_hr_bpm: { value: 170, unit: "bpm" },
      run_threshold_watts: { value: null, unit: "W" },
    } };
    renderPerformance(state.data.performance);
  });
  const current = page.locator("#currentPerformance");
  await expect(current.getByRole("rowheader", { name: "Maximale Herzfrequenz" })).toHaveCount(0);
  await expect(current.locator('[data-metric="max_hr_bpm"]')).toHaveCount(0);
  await expect(current.locator("caption")).toHaveText(["Laufen", "Radfahren"]);
  await expect(current.locator('[data-metric="cycling_w_per_kg"]')).toContainText("3,8 W/kg");
  await expect(current.locator('[data-metric="run_threshold_watts"]')).toHaveCount(0);
  await expect(current.locator('[data-metric="cycling_eftp_watts"]')).toHaveCount(0);
  await expect(current).not.toContainText("eFTP");
  await expect(page.locator("#analysisHistoryCharts")).not.toContainText("eFTP");
  await expect(page.locator("#analysisHistoryCharts").getByRole("heading", { name: "Rad-Leistung pro Gewicht" })).toHaveCount(0);
  const ftp = page.locator(".analysis-subchart").filter({ has: page.getByRole("heading", { name: "Leistungsschwelle · FTP", exact: true }) });
  await expect(ftp.locator('circle[data-series="0"]')).toHaveCount(3);
  await expect(ftp.locator(".analysis-chart-legend .analysis-legend-info")).toHaveCount(1);
  await expect(page.locator('#cyclingPowerProfile [data-power-duration="5"]')).toContainText("700 W");
  await expect(page.locator('#cyclingPowerProfile [data-power-duration="60"]')).toContainText("420 W");
  await expect(page.locator("#cyclingPowerProfile thead th")).toHaveText(["Dauer", "Leistung", "Datum"]);
  await expect(page.locator("#cyclingPowerProfile [data-power-profile-gap]")).toHaveText("Für 3 von 14 Radeinheiten fehlen vollständige Messreihen; die Bestwerte können höher liegen.");
  await expect(page.locator("#cyclingPowerProfile [data-critical-power]")).toHaveText("Schätzung Experimentell · CP (28 Tage): Rad outdoor CP 250 W · W′ 18 kJ (unsicher) · 1× Wettkampf · Rad indoor —");
  // The running critical speed sits under the running best efforts (#2265).
  await expect(page.locator("#runningBestEfforts [data-critical-power]")).toHaveText("Schätzung Experimentell · CS (28 Tage): Lauf CS 4,12 m/s · D′ 200 m (unsicher)");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});

test("@responsive Laufen and Radfahren each show only their sport", async ({ page, request }) => {
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  await page.route("**/api/analysis/power-profiles", (route) => route.fulfill({ json: { all_time: {
    power: [{ sport: "ride", duration_seconds: 300, watts: 310, status: "ok", date: "2026-10-01" }],
    running: {
      speed: [
        { sport: "run", duration_seconds: 60, speed_mps: 5, status: "ok", date: "2026-10-01", source: "Garmin Connect" },
        { sport: "run", duration_seconds: 1200, speed_mps: null, status: "unknown" },
      ],
      distance: [
        { sport: "run", distance_meters: 5000, seconds: 1188, status: "ok", date: "2026-09-20", source: "Garmin Connect" },
        { sport: "run", distance_meters: 21097.5, seconds: 5530, status: "ok", date: "2026-04-12", source: "Garmin Connect" },
      ],
    },
    cache_coverage: { records: 4, unknown_records: 0, power_records: 1, power_unknown_records: 0 },
  } } }));
  // An old Leistung link opens Laufen.
  await page.goto("/#analysis/performance");
  await expect(page).toHaveURL(/#analysis\/running$/);
  const segments = page.locator("[data-analysis-segment]");
  await expect(segments).toHaveText(["Laufen", "Radfahren", "Belastung", "Erholung"]);
  await expect(page.locator('[data-analysis-segment="running"]')).toHaveAttribute("aria-current", "page");
  const best = page.locator("#runningBestEfforts");
  // Running bests are the five race distances only; a missing best keeps its row with a dash (#2786).
  await expect(best.locator("tbody th")).toHaveText(["1 km", "5 km", "10 km", "Halbmarathon", "Marathon"]);
  await expect(best.locator('[data-running-best="distance:5000"] td')).toHaveText(["19:48", "20.09.2026"]);
  await expect(best.locator('[data-running-best="distance:21097.5"] td')).toHaveText(["1:32:10", "12.04.2026"]);
  await expect(best.locator('[data-running-best="distance:10000"] td')).toHaveText(["–", ""]);
  // A missing own best takes Garmin's personal record from the fixture with a "Garmin" chip; an own best keeps its value (#2806).
  for (const [meters, time] of [["1000", "3:41"], ["42195", "3:28:00"]]) {
    const cells = best.locator(`[data-running-best="distance:${meters}"] td`);
    await expect(cells.first()).toHaveText(`${time}Garmin`);
    await expect(cells.first().locator(".source-chip")).toHaveText("Garmin");
    await expect(cells.last()).toHaveText(/^\d{2}\.\d{2}\.\d{4}$/);
  }
  await expect(best.locator('[data-running-best="distance:5000"] .source-chip')).toHaveCount(0);
  await expect(best).not.toContainText("min/km");
  await expect(page.locator("#currentPerformance table[data-analysis-sport='run']")).toBeVisible();
  await expect(page.locator("#currentPerformance table[data-analysis-sport='ride']")).toBeHidden();
  await expect(page.locator("#cyclingPowerProfile")).toBeHidden();
  await expect(page.locator("[data-analysis-section='development-Rad']")).toBeHidden();
  await page.locator('[data-analysis-segment="cycling"]').click();
  await expect(page).toHaveURL(/#analysis\/cycling$/);
  await expect(page.locator('#cyclingPowerProfile [data-power-duration="300"]')).toContainText("310 W");
  await expect(page.locator("#currentPerformance table[data-analysis-sport='ride']")).toBeVisible();
  for (const hidden of ["#runningBestEfforts", "#performancePredictions", "#currentPerformance table[data-analysis-sport='run']", "[data-analysis-section='development-Lauf']"]) await expect(page.locator(hidden)).toBeHidden();
  await expect(page.locator("#analysisRefreshButton")).toHaveAttribute("aria-label", "Analyse aktualisieren: Radfahren");
  // A sport without current values names it in its own segment.
  await page.locator('[data-analysis-segment="running"]').click();
  await page.evaluate(() => { renderCurrentPerformance({ cycling_ftp_watts: { value: 260, unit: "W" } }, state.data.performance.history); renderAnalysisSegments(state.route); });
  await expect(page.locator("#currentPerformance p[data-analysis-sport='run']")).toBeVisible();
  await expect(page.locator("#currentPerformance p[data-analysis-sport='run']")).toHaveText("Noch keine aktuellen Werte.");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});

test("@responsive the threshold charts show the LT1 progression with gaps, heart rate and origin", async ({ page, request }) => {
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  await page.goto("/#analysis/running");
  await page.waitForFunction(() => !!state.data?.performance?.history?.body);
  const [gap, measured] = await page.evaluate(() => {
    const history = structuredClone(state.data.performance.history);
    const end = history.end;
    const weekEnd = (weeks) => addDateKey(end, 6 - ((new Date(`${end}T12:00:00Z`).getUTCDay() + 6) % 7) - 7 * weeks);
    const point = (date, value) => ({ date, value, origin: value == null ? null : "own_sessions", hr_bpm: value == null ? null : 144, hr_origin: value == null ? null : "measured" });
    history.first_thresholds = { status: "ok", run: [point(weekEnd(3), null), point(weekEnd(2), 333), point(weekEnd(1), 330), point(end, 328)], ride: [] };
    state.data.performance = { ...state.data.performance, history };
    renderAnalysisHistory(history);
    return [weekEnd(3), weekEnd(2)];
  });
  const pace = page.locator(".analysis-subchart").filter({ has: page.getByRole("heading", { name: "Schwellenpace", exact: true }) });
  await expect(pace.locator(".analysis-chart-legend")).toContainText("LT1 · aerobe Schwelle");
  // Three LT1 weeks drawn; the week without three own sessions stays a gap.
  await expect(pace.locator('circle[data-color="1"]')).toHaveCount(3);
  const marker = pace.locator(`.analysis-day-marker[data-date="${measured}"]`);
  await marker.focus();
  await page.keyboard.press("Enter");
  const readout = page.locator(`#${await marker.getAttribute("aria-describedby")}`);
  await expect(readout).toContainText("bei 144 bpm · Schätzung aus eigenen Einheiten");
  const gapMarker = pace.locator(`.analysis-day-marker[data-date="${gap}"]`);
  // The gap week keeps its LT2 reading but has no LT1 in it.
  await expect(gapMarker).toHaveCount(1);
  await expect(page.locator(`#${await gapMarker.getAttribute("aria-describedby")}`)).not.toContainText("LT1");
});
