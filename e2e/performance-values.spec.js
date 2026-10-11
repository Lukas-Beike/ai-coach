const { test, expect } = require("@playwright/test");

test("@responsive performance keeps Garmin measurements and one cycling best per duration", async ({ page, request }) => {
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  await page.route("**/api/analysis/power-profiles", (route) => route.fulfill({ json: { windows: { "90": { power: [
    { sport: "Ride", duration_seconds: 5, watts: 650, status: "ok", date: "2026-10-01" },
    { sport: "VirtualRide", duration_seconds: 5, watts: 700, status: "ok", date: "2026-10-02" },
  ] } } } }));
  await page.goto("/#analysis/performance");
  await expect(page.locator("#currentPerformance")).toBeVisible();
  await page.waitForFunction(() => !!state.data?.performance?.history?.body);
  await page.evaluate(() => {
    const history = structuredClone(state.data.performance.history);
    history.end = "2026-10-04";
    history.metrics.cycling_ftp_watts = [{ source: "Garmin Connect", points: [
      { date: "2026-10-01", value: 270 }, { date: "2026-10-02", value: 272 }, { date: "2026-10-03", value: 275 },
    ] }];
    history.cycling_power_profile = { points: [
      { duration_seconds: 60, watts: 420, status: "ok", date: "2026-10-01", source: "Intervals.icu" },
    ] };
    history.body.windows["12w"].metrics.cycling_w_per_kg = [
      { source: "Garmin Connect", points: [{ date: "2026-10-03", value: 3.8 }] },
      { source: "Intervals.icu", points: [{ date: "2026-10-03", value: 3.9 }] },
    ];
    state.data.performance = { ...state.data.performance, history, metrics: {
      ...state.data.performance.metrics,
      running_max_hr_bpm: { value: 190, unit: "bpm" }, cycling_max_hr_bpm: { value: 185, unit: "bpm" },
    } };
    renderPerformance(state.data.performance);
  });
  const current = page.locator("#currentPerformance");
  await expect(current.getByRole("rowheader", { name: "Maximale Herzfrequenz" })).toHaveCount(1);
  await expect(current.locator('[data-metric="max_hr_bpm"]')).toContainText("190 bpm");
  await expect(current.locator('[data-metric="cycling_w_per_kg"]')).toContainText("3,8 W/kg");
  const order = await current.evaluate((root) => {
    const tables = root.querySelectorAll(".current-performance-table");
    const general = tables[0].getBoundingClientRect();
    const running = tables[1].getBoundingClientRect();
    return { generalHeight: general.height, generalBottom: general.bottom, runningTop: running.top };
  });
  expect(order.generalHeight).toBeGreaterThan(0);
  expect(order.generalBottom).toBeLessThanOrEqual(order.runningTop);
  await expect(page.locator("#analysisHistoryCharts").getByRole("heading", { name: "Rad-Leistung pro Gewicht" })).toHaveCount(0);
  const ftp = page.locator(".analysis-subchart").filter({ has: page.getByRole("heading", { name: "Leistungsschwelle · FTP / eFTP", exact: true }) });
  await expect(ftp.locator('circle[data-series="0"]')).toHaveCount(3);
  await expect(page.locator('#cyclingPowerProfile [data-power-duration="5"]')).toContainText("700 W");
  await expect(page.locator('#cyclingPowerProfile [data-power-duration="60"]')).toContainText("420 W");
  await expect(page.locator("#cyclingPowerProfile thead th")).toHaveText(["Dauer", "Leistung"]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
