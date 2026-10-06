const { test, expect } = require("@playwright/test");

test("@responsive chart readings keep their coordinates and legible labels", async ({ page }) => {
  await page.goto("/#analysis/performance");
  await expect(page.locator("#appShell")).toBeVisible();
  const result = await page.evaluate(() => {
    const points = [{ date: "2026-10-01", value: 53.5 }, { date: "2026-10-04", value: 54 }, { date: "2026-10-08", value: 54.5 }];
    const series = [{ label: "VO2max", points, currentPoint: { date: "2026-10-08", value: 53 }, cadenceDays: 7 }];
    const chart = analysisChart("Coordinates", series, "ml/kg/min", "2026-10-01", "2026-10-08", "", { sparse: true });
    document.querySelector("#analysisHistoryCharts").replaceChildren(chart);
    const path = chart.querySelector("path[data-series]").getAttribute("d");
    const dotsOnPath = [...chart.querySelectorAll("circle")].every((dot) => path.includes(`${Number(dot.getAttribute("cx")).toFixed(2)},${Number(dot.getAttribute("cy")).toFixed(2)}`));
    const sleep = analysisChart("Sleep", [{ label: "Sleep", bars: true, points: [{ date: "2026-10-01", value: 8.2 }, { date: "2026-10-08", value: 6.5 }] }], "h", "2026-10-01", "2026-10-08", "");
    chart.after(sleep);
    const bars = [...sleep.querySelectorAll(".recovery-sleep-bar")];
    const bar = bars.sort((a, b) => Number(a.getAttribute("y")) - Number(b.getAttribute("y")))[0];
    const label = [...sleep.querySelectorAll(".analysis-point-value")].find((node) => node.textContent === "8:12");
    return {
      currentLines: chart.querySelectorAll(".analysis-current-line").length,
      dotsOnPath,
      labelCentered: Math.abs(Number(label.getAttribute("x")) - Number(bar.getAttribute("x")) - Number(bar.getAttribute("width")) / 2) < .01,
      labelAboveBar: Number(bar.getAttribute("y")) - Number(label.getAttribute("y")),
      halo: getComputedStyle(label).paintOrder,
    };
  });
  expect(result).toEqual({ currentLines: 0, dotsOnPath: true, labelCentered: true, labelAboveBar: 10, halo: "stroke" });
});

test("@responsive recovery, power, training focus, season and calendar profiles show local facts", async ({ page, request }) => {
  const seed = await request.get("/api/fixture/features");
  expect(seed.ok(), await seed.text()).toBeTruthy();
  await page.goto("/#analysis/performance");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator("#strengthProgress, #strengthTemplates")).toHaveCount(0);
  await page.evaluate(async () => { await applyNavigationRoute("analysis/performance", { historyMode: "replace" }); });
  await expect(page.locator("#analysisHistoryCharts")).toBeVisible();
  await expect(page.locator("#sessionPerformance")).toBeHidden();
  await expect(page.locator("#trainingReport")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Woche", exact: true })).toHaveCount(0);
  await page.evaluate(async () => { await applyNavigationRoute("analysis/load", { historyMode: "replace" }); });
  const report = page.locator("#sessionPerformance");
  await expect(report.getByRole("heading", { name: /^Trainingsfokus/ })).toBeVisible();
  expect((await report.boundingBox()).y).toBeGreaterThan((await page.locator("#analysisLoadCharts").boundingBox()).y);
  await expect(page.locator("#analysisHistoryCharts .analysis-period-controls")).toHaveCount(0);
  await expect(report.getByText("Leicht aerob", { exact: true })).toBeVisible();
  await expect(report.getByText("Hoch aerob", { exact: true })).toBeVisible();
  await expect(report.getByText("Anaerob", { exact: true })).toBeVisible();
  await expect(report.locator(".training-focus-share")).toBeVisible();
  const focusInfo = report.locator(".analysis-legend-info").first();
  await focusInfo.click();
  await expect(report.locator(".analysis-info-tooltip:popover-open")).toContainText("3 erfasste Garmin-Einheiten");
  await expect(report.locator(".analysis-info-tooltip:popover-open")).toContainText("erfasste Daten");
  await page.keyboard.press("Escape");
  const zones = page.locator("#trainingZoneCharts");
  await expect(zones.getByRole("heading", { name: "HF-Zonen" })).toBeVisible();
  await expect(zones.getByRole("heading", { name: "Power-Zonen" })).toBeVisible();
  await expect(zones.locator("details")).toHaveCount(0);
  expect((await zones.boundingBox()).y).toBeGreaterThan((await report.boundingBox()).y);
  await page.evaluate(() => renderSyncStatus({ running: false, message: null }));
  await expect(zones.locator("progress")).toHaveCount(12);
  await page.evaluate(async () => { await applyNavigationRoute("analysis/performance", { historyMode: "replace" }); });
  const periods = await page.evaluate(() => {
    const history = state.data.performance.history;
    const focus = state.data.performance.training_focus;
    return {
      expected: `${dateLabel(addDateKey(history.end, -((new Date(`${history.end}T12:00:00Z`).getUTCDay() + 6) % 7) - 77))} bis ${dateLabel(history.end)}`,
      same: focus.end === history.end && focus.start === addDateKey(history.end, -27),
      titles: [...document.querySelectorAll("#analysisHistoryCharts svg > title")].map((node) => node.textContent),
    };
  });
  expect(periods.same).toBeTruthy();
  expect(periods.titles.length).toBeGreaterThan(0);
  await expect(page.locator("#analysisHistoryCharts .analysis-sparse-note:visible")).toHaveCount(0);
  await page.locator("#analysisHistoryCharts").getByRole("button", { name: "FTP", exact: true }).click();
  await expect(page.locator("#analysisHistoryCharts .analysis-info-tooltip:popover-open")).toContainText(/Seit .+: \+\d+(?:,\d+)? W/);
  await page.keyboard.press("Escape");
  for (const title of periods.titles) expect(title).toContain(periods.expected);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();

  await page.evaluate(async () => { await applyNavigationRoute("analysis/recovery", { historyMode: "replace" }); });
  await expect(page.getByRole("heading", { name: "Aktuelle Erholung", exact: true })).toHaveCount(0);
  const recovery = page.locator("#personalRecovery");
  await expect(recovery.locator("svg")).toHaveCount(3);
  await expect(recovery.locator(".analysis-chart-card").first()).toContainText("Erholung · Letzte 14 Tage");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();

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
  await expect(recovery.locator(".analysis-period-controls")).toHaveCount(1);
  await recovery.getByRole("button", { name: "12 Wochen", exact: true }).click();
  await expect(recovery.locator(".analysis-chart-card").first()).toContainText("Erholung · Letzte 12 Wochen");
  await expect(recovery.locator(".analysis-subchart")).toHaveCount(3);

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

test("@responsive equipment keeps local authority and groups archived sources", async ({ page }) => {
  await page.route("**/api/analysis/training-records", (route) => route.fulfill({ json: { equipment: {
    items: [
      { id: "local-active", name: "Local running shoes", sport: "Run", kind: "shoes", status: "active", garmin_status: "Retired", revision: 1, usage: { distance_km: 125, hours: 0, assigned_sessions: 2 }, lifetime: { usage_km: 125, target_km: 100, percent: 125, progress_percent: 100 } },
      { id: "local-retired-component", name: "Retired chain", sport: "Ride", kind: "component", status: "archived", garmin_uuid: "local-garmin-chain", revision: 1, usage: { distance_km: 50, hours: 0, assigned_sessions: 1 }, lifetime: { usage_km: 50, target_km: 100, percent: 50, progress_percent: 50 } },
      { id: "local-unlinked-component", name: "Coach-only retired cassette", sport: "Ride", kind: "component", status: "archived", revision: 1, usage: { distance_km: 0, hours: 0, assigned_sessions: 0 } },
    ],
    garmin_items: [
      { id: "garmin-active", name: "Garmin active shoes", kind: "Running Shoes", status: "active", garmin_status: "Active", distance_km: 25, goal_km: 50, lifetime: { usage_km: 25, target_km: 50, percent: 50, progress_percent: 50 } },
      { id: "garmin-retired-chain", name: "Garmin retired chain", kind: "Bike component", status: "archived", garmin_status: "Retired", distance_km: 150, goal_km: 100, lifetime: { usage_km: 150, target_km: 100, percent: 150, progress_percent: 100 } },
    ],
  } } }));
  await page.goto("/#more/equipment");
  await expect(page.locator("#appShell")).toBeVisible();
  const bikePanel = page.locator("#equipmentPanel-bike");
  const archive = bikePanel.locator("details.equipment-archive");
  await expect(archive).toHaveCount(1);
  await expect(archive).not.toHaveAttribute("open", "");
  await expect(archive.locator("summary")).toContainText("3");
  await archive.locator("summary").click();
  await expect(archive.getByRole("heading", { name: "Retired chain", exact: true })).toBeAttached();
  await expect(archive.getByRole("heading", { name: "Garmin retired chain", exact: true })).toBeAttached();
  const unlinkedLocal = archive.locator("section").filter({ hasText: "Coach-only retired cassette" });
  await expect(unlinkedLocal).toContainText("Revision 1");
  await page.getByRole("tab", { name: "Laufschuhe" }).click();
  const runPanel = page.locator("#equipmentPanel-run");
  const localCard = runPanel.locator(".garmin-equipment-card").filter({ hasText: "Local running shoes" });
  const garminCard = runPanel.locator(".garmin-equipment-card").filter({ hasText: "Garmin active shoes" });
  await expect(localCard.getByRole("heading", { name: "Local running shoes" })).toBeAttached();
  await expect(localCard.locator("progress")).toHaveAttribute("value", "100");
  await expect(localCard).toContainText("125%");
  await expect(localCard).toContainText("Ziel überschritten");
  await expect(localCard).toContainText("Statuskonflikt");
  await expect(localCard.locator("progress")).toHaveAttribute("aria-label", /Lebensdauer/);
  await expect(garminCard.locator("progress")).toHaveAttribute("value", "50");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
