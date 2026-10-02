const { test, expect } = require("@playwright/test");

test("@responsive recovery, power, training focus, season and calendar profiles show local facts", async ({ page, request }) => {
  const seed = await request.get("/api/fixture/features");
  expect(seed.ok(), await seed.text()).toBeTruthy();
  await page.goto("/#analysis/performance");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator("#strengthProgress, #strengthTemplates")).toHaveCount(0);
  await page.evaluate(async () => { await applyNavigationRoute("analysis/performance", { historyMode: "replace" }); });
  const report = page.locator("#sessionPerformance");
  await expect(page.locator("#trainingReport")).toBeHidden();
  await expect(report.getByRole("heading", { name: /^Trainingsfokus/ })).toBeVisible();
  await expect(report.getByText("Leicht aerob", { exact: true })).toBeVisible();
  await expect(report.getByText("Hoch aerob", { exact: true })).toBeVisible();
  await expect(report.getByText("Anaerob", { exact: true })).toBeVisible();
  await expect(report.locator(".training-focus-share")).toBeVisible();
  await expect(report.getByRole("heading", { name: "HF-Zonen" })).toBeHidden();
  await report.getByText("Zonen im Detail", { exact: true }).click();
  await expect(report.getByRole("heading", { name: "HF-Zonen" })).toBeVisible();
  await expect(report.getByRole("heading", { name: "Power-Zonen" })).toBeVisible();
  await page.evaluate(() => renderSyncStatus({ running: false, message: null }));
  await expect(report.locator("progress")).toHaveCount(12);
  const periods = await page.evaluate(() => {
    const history = state.data.performance.history;
    const focus = state.data.performance.training_focus;
    return {
      expected: `${dateLabel(focus.start)} bis ${dateLabel(focus.end)}`,
      same: focus.end === history.end && focus.start === addDateKey(history.end, -55),
      titles: [...document.querySelectorAll("#analysisHistoryCharts svg > title")].map((node) => node.textContent),
    };
  });
  expect(periods.same).toBeTruthy();
  expect(periods.titles).toHaveLength(2);
  for (const title of periods.titles) expect(title).toContain(periods.expected);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();

  await page.evaluate(async () => { await applyNavigationRoute("analysis/recovery", { historyMode: "replace" }); });
  await expect(page.getByRole("heading", { name: "Aktuelle Erholung", exact: true })).toHaveCount(0);
  const recovery = page.locator("#personalRecovery");
  await expect(recovery.locator("svg")).toHaveCount(2);
  await expect(recovery.getByRole("img", { name: "Erholung · Aktuelle Woche: datierter Verlauf. Einzelwerte stehen unter Werte ansehen." })).toBeVisible();
  for (const metric of ["Schlafdauer", "HRV", "Ruhepuls"]) await expect(recovery.getByRole("button", { name: new RegExp(`^${metric}:`) })).toHaveCount(2);
  await expect(recovery.locator(".analysis-chart-card").first()).toContainText("Erholung · Aktuelle Woche");
  await expect(recovery.locator("svg path[data-color='1']").first()).toHaveAttribute("d", /M.*M/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.locator("#personalRecovery").getByText("Was beeinflusst deine Erholung?", { exact: true }).click();
  await expect(page.locator("#personalRecovery").getByText(/Mindestens zehn gemessene Tage je Gruppe/).first()).toBeVisible();

  await page.evaluate(() => {
    const report = { ...state.data.performance.personal_recovery, as_of: "2026-10-02" };
    const week = addDateKey(report.as_of, -((new Date(`${report.as_of}T12:00:00Z`).getUTCDay() + 6) % 7));
    const baselines = selectedRecoveryBaselines(report).map((item) => ({ ...item,
      observed_at: report.as_of,
      history: [{ date: addDateKey(week, -49), value: 7 }, { date: week, value: 7 }, { date: report.as_of, value: 9 }],
    }));
    renderPersonalRecovery({ ...report, baselines: [...baselines,
      ...baselines.map((item) => ({ ...item, source: "Garmin Connect", history: item.history.map((point) => ({ ...point, value: 99 })) })),
    ] });
  });
  const weeklyRecovery = recovery.locator(".analysis-chart-card").nth(1);
  await expect(weeklyRecovery.getByRole("button", { name: /^Schlafdauer: 8 h/ })).toBeVisible();
  await expect(weeklyRecovery.locator("tbody tr")).toHaveCount(2);
  await expect(weeklyRecovery.locator(".analysis-chart-legend li")).toHaveCount(3);
  await expect(weeklyRecovery).not.toContainText("99 h");

  await page.evaluate(async () => { await applyNavigationRoute("plan/season", { historyMode: "replace" }); });
  await expect(page.locator("#seasonPreparation").getByRole("heading", { name: /Fixture cycling target/ }).first()).toBeVisible();
  await expect(page.locator("#seasonPreparation").getByText(/Wochen mit erfasstem sportartspezifischem Training/).first()).toBeVisible();
  await page.locator("#seasonPreparation").getByRole("button", { name: /Szenarien vergleichen/ }).first().click();
  await expect(page.locator("#seasonPreparation").getByText(/Lokales Standardmodell/).first()).toBeVisible();

  await page.evaluate(async () => { await applyNavigationRoute("plan/overview", { historyMode: "replace" }); });
  await expect(page.locator(".planned-week[open] .planned-day").first()).toBeVisible();
  await expect(page.locator(".planned-day-metrics, .planned-day-form")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Pers.nliche Erholung/ })).toHaveCount(0);
  await expect(page.locator(".planned-insights-title").filter({ hasText: "Check-in & Erholung" })).toHaveCount(0);
  await expect(page.locator(".calendar-workout-profile[aria-label='Geplantes Intervallprofil']").first()).toBeVisible();
  await expect(page.locator(".calendar-workout-profile[aria-label='Aufgezeichnetes Belastungsprofil']").first()).toBeAttached();

  await page.evaluate(async () => { await applyNavigationRoute("more/equipment", { historyMode: "replace" }); });
  await expect(page.locator("#equipmentItems").getByRole("heading", { name: "Fixture Garmin bike" })).toBeVisible();
  await expect(page.locator("#equipmentItems").getByText("25 km", { exact: true })).toBeVisible();
  await expect(page.locator("#equipmentItems progress")).toHaveAttribute("value", "25");
  const localGear = page.locator("#equipmentItems details");
  await localGear.locator("summary").click();
  await expect(localGear.getByRole("heading", { name: "Fixture road bike" }).first()).toBeVisible();
  await expect(localGear).toContainText("Revision 1");
  await expect(localGear).toContainText("1 zugeordnete Einheiten");
  await expect(localGear).toContainText("Keine Wartung erfasst.");

  await page.evaluate(async () => { await applyNavigationRoute("more/profile", { historyMode: "replace" }); });
  await expect(page.locator("#profilePanel").getByRole("heading", { name: "Profil", exact: true })).toBeVisible();
  await expect(page.locator("#equipmentItems")).toBeHidden();
  await page.evaluate(async () => { await applyNavigationRoute("more/appearance", { historyMode: "replace" }); });
  const calendarSettings = page.locator("details").filter({ has: page.locator("#calendarDisplayForm") });
  await expect(calendarSettings).toBeVisible();
  await calendarSettings.locator("summary").click();
  await expect(page.locator("#calendarDisplayPastWeeks")).toBeVisible();
  await page.evaluate(async () => { await applyNavigationRoute("more/operations", { historyMode: "replace" }); });
  await expect(calendarSettings).toBeHidden();
  await page.evaluate(async () => { await applyNavigationRoute("nutrition/diary", { historyMode: "replace" }); });
  await expect(page.locator('[data-nutrition-segment="fueling"], #trainingFueling, #nutritionLog, #nutritionDefine')).toHaveCount(0);
  await expect(page.locator("#nutritionPanel").getByRole("button", { name: /Coach/ })).toHaveCount(0);
  await expect(page.locator("#seasonPreparation").getByRole("button", { name: /Vorbereitung besprechen|Vorschau anfragen/ })).toHaveCount(0);
});

test("@responsive local equipment and maintenance remain visible without Garmin inventory", async ({ page }) => {
  await page.route("**/api/analysis/training-records", route => route.fulfill({ json: { equipment: {
    garmin_items: [], items: [{name: "Saved bike", kind: "bike", revision: 3,
      usage: {distance_km: 120, hours: 6, assigned_sessions: 4, maintenance_distance_km: 20,
        maintenance_hours: 1, maintenance_due: null, maintenance_coverage: "partial"},
      maintenance: [{date: "2026-09-30", notes: "<img src=x> Chain replaced"}] }],
  } } }));
  await page.goto("/#more/equipment");
  const gear = page.locator("#equipmentItems");
  await expect(gear.locator("details summary")).toBeVisible();
  await gear.locator("details summary").click();
  await expect(gear.getByRole("heading", {name: "Saved bike"})).toBeVisible();
  await expect(gear).toContainText("Revision 3");
  await expect(gear).toContainText("120 km");
  await expect(gear).toContainText("4 zugeordnete Einheiten");
  await expect(gear).toContainText("Wartungsstand unklar");
  await expect(gear).toContainText("Chain replaced");
  await expect(gear.locator("img")).toHaveCount(0);
});
