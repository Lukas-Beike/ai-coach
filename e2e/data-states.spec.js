const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

// #1783: loading, not configured, no data yet and failed reads look different.
const POWER_PROFILES = "/api/analysis/power-profiles";
const ANALYSIS_TABS = [
  ["load", "Noch keine Belastungsdaten"],
  ["performance", "Noch keine Leistungsdaten"],
  ["recovery", "Noch keine Erholungsdaten"],
  ["sessions", "Noch keine Einheiten"],
];

async function openAnalysis(page, segment) {
  await page.goto(`/#analysis/${segment}`);
  await expect(page.locator("#appShell")).toBeVisible();
  await page.waitForFunction(() => AppState.state.initialStateLoaded);
}

test("@responsive an empty install shows one empty card with one action per analysis tab", async ({ page }) => {
  await openAnalysis(page, "load");
  const connected = await page.evaluate(() => Boolean(AppState.state.data?.garmin?.configured || AppState.state.data?.wahoo?.connected));
  const card = page.locator("#analysisEmptyState .empty-state");
  for (const [segment, title] of ANALYSIS_TABS) {
    await page.evaluate((target) => { location.hash = target; }, `#analysis/${segment}`);
    await expect(card).toBeVisible();
    await expect(card.locator("strong")).toHaveText(title);
    await expect(card.locator("a, button")).toHaveCount(1);
    await expect(card.locator("a, button")).toHaveText(connected ? "Jetzt abgleichen" : "Anbindung einrichten");
    await expect(page.locator("#dataPanel")).not.toContainText("Keine Daten:");
    await expect(card).not.toContainText("Intervals.icu");
    for (const id of ["sessionPerformance", "analysisLoadCharts", "trainingZoneCharts", "currentPerformance", "analysisHistoryCharts", "activityAnalysis"]) {
      await expect(page.locator(`#${id}`)).toBeHidden();
    }
  }
  expect((await new AxeBuilder({ page }).include("#dataPanel").analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

  // The action follows the connection state: no source leads to the connections, a source to a sync.
  await page.evaluate(() => { AppState.state.data.garmin = { ...AppState.state.data.garmin, configured: false }; AppState.state.data.wahoo = { ...AppState.state.data.wahoo, connected: false }; renderAnalysisSegments(AppState.state.route); });
  await expect(card.locator("span")).toHaveText("Garmin oder Wahoo ist nicht verbunden.");
  await expect(card.getByRole("link", { name: "Anbindung einrichten" })).toHaveAttribute("href", "#more/connections");
  await page.evaluate(() => { AppState.state.data.garmin = { ...AppState.state.data.garmin, configured: true }; renderAnalysisSegments(AppState.state.route); });
  await expect(card.locator("span")).toHaveText("Noch keine Daten abgeglichen.");
  await expect(card.getByRole("button", { name: "Jetzt abgleichen" })).toBeVisible();
});

test("@responsive a failed analysis read shows an error with retry instead of a permanent loading line", async ({ page }) => {
  let fail = true;
  let requests = 0;
  await page.route(`**${POWER_PROFILES}`, (route) => {
    requests += 1;
    return fail
      ? route.fulfill({ status: 503, json: { error: "E2E fixture: Leistungsprofil nicht erreichbar" } })
      : route.fulfill({ json: { windows: { "90": { power: [{ sport: "Ride", duration_seconds: 5, watts: 640, status: "ok", date: "2026-10-01", source: "Garmin Connect" }] } } } });
  });
  await openAnalysis(page, "performance");
  const profile = page.locator("#cyclingPowerProfile");
  const error = profile.locator(".error-state");
  await expect(error).toBeVisible();
  await expect(error).toHaveAttribute("role", "alert");
  await expect(error.locator("strong")).toHaveText("Konnte nicht geladen werden.");
  await expect(profile).not.toContainText("wird geladen");
  // A failed read is not "no data": the tab keeps its sections and shows no empty card.
  await expect(page.locator("#analysisEmptyState")).toBeHidden();
  expect((await new AxeBuilder({ page }).include("#cyclingPowerProfile").analyze()).violations).toEqual([]);

  fail = false;
  await error.getByRole("button", { name: "Erneut versuchen" }).click();
  await expect(profile.locator("[data-power-duration='5'] td")).toHaveText("640 W");
  await expect(profile.locator("[data-power-duration='60'] td.value-missing")).toHaveText("nicht erfasst");
  await expect(profile.locator(".error-state")).toHaveCount(0);
  expect(requests).toBe(2);
});

test("@responsive a hanging analysis read times out into the retry state", async ({ page }) => {
  test.setTimeout(60_000);
  await page.route(`**${POWER_PROFILES}`, () => { /* never answers */ });
  await openAnalysis(page, "performance");
  const profile = page.locator("#cyclingPowerProfile");
  await expect(profile.locator(".loading-state")).toHaveText("Leistungsprofil wird geladen…");
  await expect(profile.locator(".loading-state")).toHaveAttribute("aria-busy", "true");
  await expect(profile.locator(".error-state")).toContainText("15 Sekunden", { timeout: 25_000 });
  await expect(profile.locator(".loading-state")).toHaveCount(0);
  await expect(profile.getByRole("button", { name: "Erneut versuchen" })).toBeVisible();
});

test("@responsive a failed session list read offers a retry", async ({ page }) => {
  let fail = true;
  await page.route(/\/api\/activities\?limit=/, (route) => (fail
    ? route.fulfill({ status: 503, json: { error: "E2E fixture: Einheiten nicht erreichbar" } })
    : route.fallback()));
  await openAnalysis(page, "sessions");
  const list = page.locator("#activityAnalysis");
  await expect(list.locator(".error-state")).toBeVisible();
  await expect(page.locator("#analysisEmptyState")).toBeHidden();
  fail = false;
  await list.getByRole("button", { name: "Erneut versuchen" }).click();
  // The empty fixture has no sessions, so the retry ends in the tab's one empty card.
  await expect(page.locator("#analysisEmptyState .empty-state strong")).toHaveText("Noch keine Einheiten");
  await expect(list).toBeHidden();
});
