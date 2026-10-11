const { test, expect } = require("@playwright/test");

const ENDURANCE = "/api/analysis/endurance";
const POWER_PROFILES = "/api/analysis/power-profiles";
const TRAINING_RECORDS = "/api/analysis/training-records";
const REPORT_PATHS = [ENDURANCE, POWER_PROFILES, TRAINING_RECORDS];

function trackReportRequests(page) {
  const counts = new Map();
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (REPORT_PATHS.includes(path)) counts.set(path, (counts.get(path) || 0) + 1);
  });
  return () => Object.fromEntries(REPORT_PATHS.map((path) => [path, counts.get(path) || 0]));
}

async function mockReports(page) {
  await page.route(`**${ENDURANCE}`, (route) => route.fulfill({ json: { activities: [] } }));
  await page.route(`**${POWER_PROFILES}`, (route) => route.fulfill({ json: {
    windows: { "90": { power: [
      ...[5, 60, 300, 1200].map((duration_seconds) => ({ sport: "Ride", duration_seconds, watts: 250, status: "ok", date: "2026-10-01", source: "Intervals.icu" })),
      { sport: "VirtualRide", duration_seconds: 3600, watts: 210, status: "ok", date: "2026-10-02", source: "Intervals.icu" },
    ] } },
  } }));
  await page.route(`**${TRAINING_RECORDS}`, (route) => route.fulfill({ json: {
    equipment: { items: [], garmin_items: [] },
  } }));
}

async function waitForInitialState(page) {
  await page.goto("/#coach");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.waitForFunction(() => AppState.state.initialStateLoaded);
}

async function routeTo(page, hash) {
  await page.evaluate((target) => { location.hash = target; }, hash);
}

test("@responsive cycling power profile loads only on performance and keeps unknown durations empty", async ({ page }) => {
  await mockReports(page);
  const reportCounts = trackReportRequests(page);
  await waitForInitialState(page);
  expect(reportCounts()).toEqual({ [ENDURANCE]: 0, [POWER_PROFILES]: 0, [TRAINING_RECORDS]: 0 });

  await routeTo(page, "#analysis/performance");
  await expect(page.locator("#dataPanel")).toHaveClass(/active/);
  await expect(page.locator("#performancePredictions")).toBeVisible();
  await expect(page.locator("#cyclingPowerProfile tbody tr")).toHaveCount(5);
  await expect(page.locator("#cyclingPowerProfile [data-power-duration='5'] td")).toHaveText(["250 W", "—"]);
  await expect(page.locator("#cyclingPowerProfile [data-power-duration='3600'] td")).toHaveText(["—", "210 W"]);
  await expect(page.locator("#cyclingPowerProfile")).toContainText("letzte 90 Tage");
  expect(await page.locator("#cyclingPowerProfile").evaluate((element) => element.closest("[data-analysis-section]").dataset.analysisSection)).toBe("development-Rad");
  expect(reportCounts()).toEqual({ [ENDURANCE]: 0, [POWER_PROFILES]: 1, [TRAINING_RECORDS]: 0 });
});

test("@responsive cold start on performance fetches only the power profile", async ({ page }) => {
  await mockReports(page);
  const reportCounts = trackReportRequests(page);
  await page.goto("/#analysis/performance");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.waitForFunction(() => AppState.state.initialStateLoaded);
  await expect(page.locator("#performancePredictions")).toBeVisible();
  await expect(page.locator("#cyclingPowerProfile tbody tr")).toHaveCount(5);
  expect(reportCounts()).toEqual({ [ENDURANCE]: 0, [POWER_PROFILES]: 1, [TRAINING_RECORDS]: 0 });
});

test("@responsive cycling power profile stays cached across navigation and chart rerenders", async ({ page }) => {
  await mockReports(page);
  const reportCounts = trackReportRequests(page);
  await waitForInitialState(page);

  await routeTo(page, "#analysis/performance");
  await expect(page.locator("#performancePredictions")).toBeVisible();
  await expect(page.locator("#cyclingPowerProfile tbody tr")).toHaveCount(5);
  const afterFirstVisit = reportCounts();
  await page.evaluate(() => renderAnalysisHistory(state.data.performance.history));
  await expect(page.locator("#cyclingPowerProfile tbody tr")).toHaveCount(5);

  await routeTo(page, "#coach");
  await expect(page.locator("#chatPanel")).toHaveClass(/active/);
  await routeTo(page, "#analysis/performance");
  await expect(page.locator("#dataPanel")).toHaveClass(/active/);
  await expect(page.locator("#performancePredictions")).toBeVisible();
  expect(reportCounts()).toEqual(afterFirstVisit);
});

test("@responsive equipment records load only on the equipment route and stay cached", async ({ page }) => {
  await mockReports(page);
  const reportCounts = trackReportRequests(page);
  await waitForInitialState(page);
  expect(reportCounts()[TRAINING_RECORDS]).toBe(0);

  await routeTo(page, "#more/equipment");
  await expect(page.locator("#equipmentItems").getByRole("heading", { name: "Ausrüstung und Wartung" })).toBeVisible();
  expect(reportCounts()[TRAINING_RECORDS]).toBe(1);

  await routeTo(page, "#coach");
  await expect(page.locator("#chatPanel")).toHaveClass(/active/);
  await routeTo(page, "#more/equipment");
  await expect(page.locator("#equipmentItems").getByRole("heading", { name: "Ausrüstung und Wartung" })).toBeVisible();
  expect(reportCounts()[TRAINING_RECORDS]).toBe(1);
});
