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
    best: [{ sport: "Ride", duration_seconds: 300, watts: 250, date: "2026-10-01" }],
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

test("@responsive analysis reports stay off the coach start and load once on analysis", async ({ page }) => {
  await mockReports(page);
  const reportCounts = trackReportRequests(page);
  await waitForInitialState(page);
  expect(reportCounts()).toEqual({ [ENDURANCE]: 0, [POWER_PROFILES]: 0, [TRAINING_RECORDS]: 0 });

  await routeTo(page, "#analysis/performance");
  await expect(page.locator("#dataPanel")).toHaveClass(/active/);
  await expect(page.locator("#existingPerformanceReports").getByRole("heading", { name: "Beste Fenster je Aktivität" })).toBeVisible();
  expect(reportCounts()).toEqual({ [ENDURANCE]: 1, [POWER_PROFILES]: 1, [TRAINING_RECORDS]: 0 });
});

test("@responsive cold start on analysis requests each report exactly once", async ({ page }) => {
  await mockReports(page);
  const reportCounts = trackReportRequests(page);
  await page.goto("/#analysis/performance");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.waitForFunction(() => AppState.state.initialStateLoaded);
  await expect(page.locator("#existingPerformanceReports").getByRole("heading", { name: "Beste Fenster je Aktivität" })).toBeVisible();
  expect(reportCounts()).toEqual({ [ENDURANCE]: 1, [POWER_PROFILES]: 1, [TRAINING_RECORDS]: 0 });
});

test("@responsive analysis reports are reused across navigation until the data changes", async ({ page }) => {
  await mockReports(page);
  const reportCounts = trackReportRequests(page);
  await waitForInitialState(page);

  await routeTo(page, "#analysis/performance");
  await expect(page.locator("#existingPerformanceReports").getByRole("heading", { name: "Beste Fenster je Aktivität" })).toBeVisible();
  const afterFirstVisit = reportCounts();

  await routeTo(page, "#coach");
  await expect(page.locator("#chatPanel")).toHaveClass(/active/);
  await routeTo(page, "#analysis/performance");
  await expect(page.locator("#dataPanel")).toHaveClass(/active/);
  await expect(page.locator("#existingPerformanceReports").getByRole("heading", { name: "Beste Fenster je Aktivität" })).toBeVisible();
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
