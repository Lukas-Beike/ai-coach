const { test, expect } = require("@playwright/test");

test("@responsive activity details preserve calendar without Coach shortcuts", async ({ page, request }) => {
  const seed = await request.get("/api/fixture/activity");
  expect(seed.ok()).toBeTruthy();
  await page.goto("/#plan/overview");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.evaluate(async () => { await applyNavigationRoute("plan/overview", { historyMode: "replace" }); });
  const entry = page.locator(".planned-entry").filter({ hasText: "Synthetic ride <img src=x>" }).first();
  await entry.locator("summary").click();
  const open = entry.getByRole("button", { name: "Aktivität analysieren" });
  await open.click();
  const dialog = page.getByRole("dialog", { name: "Synthetic ride <img src=x>" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("img", { name: "Leistung, Zeitachse in Minuten" })).toBeVisible();
  await expect(dialog.getByText(/Diagramme vereinfacht/)).toBeVisible();
  expect(await dialog.locator(".activity-series").first().locator("svg text").count()).toBeGreaterThan(3);
  await dialog.locator(".activity-values summary").first().click();
  await expect(dialog.locator(".activity-values table tbody tr").first()).toBeVisible();
  expect(await dialog.locator("img").count()).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await dialog.getByRole("button", { name: "Zurück zum Kalender" }).click();
  await expect(entry).toHaveAttribute("open", "");
  await expect(open).toBeFocused();
  await open.click();
  await page.goBack();
  await expect(dialog).not.toBeVisible();
  await expect(entry).toHaveAttribute("open", "");
  await open.click();
  await expect(dialog.getByRole("button", { name: "Feedback speichern" })).toBeVisible();
  await dialog.getByLabel("Session-RPE (0–10)").fill("6.5");
  await dialog.getByLabel("Abweichungsgrund").fill("Heat");
  await dialog.getByLabel("Notizen").fill("Synthetic feedback");
  await dialog.getByRole("button", { name: "Feedback speichern" }).click();
  await expect(dialog.locator('[role="status"]').filter({ hasText: "Feedback gespeichert" })).toBeVisible();
  await dialog.getByRole("button", { name: "Zurück zum Kalender" }).click();
  await page.reload();
  const response = await request.get("/api/activities/FixtureCase-1");
  const payload = await response.json();
  expect(payload.detail_data.full_resolution).toBe(true);
  expect(payload.activity.streams.time.length).toBe(2000);
  expect(payload.activity_feedback.session_rpe).toBe(6.5);
  expect(payload.activity_feedback.notes).toBe("Synthetic feedback");
});


test("@responsive Garmin charts select named measurements and athlete maintenance dates", async ({ page }) => {
  await page.goto("/#analysis/load");
  await expect(page.locator("#appShell")).toBeVisible();
  const values = await page.evaluate(() => ({
    endurance: providerMetricValue("endurance_score", { timestamp: 123, overallScore: 700 }),
    tolerance: providerMetricValue("running_tolerance", { age: 35, runningTolerance: 42 }),
    unknown: providerMetricValue("endurance_score", { timestamp: 123 }) ?? null,
    invalid: providerMetricValue("running_tolerance", { tolerance: "42" }) ?? null,
  }));
  expect(values).toEqual({ endurance: 700, tolerance: 42, unknown: null, invalid: null });
  const date = await page.evaluate(async () => {
    const previousApi = api;
    const previousState = state.data;
    const RealDate = Date;
    let sent;
    try {
      state.data = { profile: { timezone: "Pacific/Honolulu" } };
      globalThis.Date = class extends RealDate {
        constructor(...args) { super(...(args.length ? args : ["2026-10-07T00:30:00Z"])); }
      };
      api = async (_url, options) => { if (options?.body) sent = JSON.parse(options.body); return { items: [] }; };
      maintenanceButton({ id: "synthetic-equipment" }).click();
      await Promise.resolve();
      return sent.date;
    } finally {
      api = previousApi;
      state.data = previousState;
      globalThis.Date = RealDate;
    }
  });
  expect(date).toBe("2026-10-06");
});

test("@responsive activity stream aliases render once with canonical preference", async ({ page }) => {
  await page.goto("/#plan/overview");
  await expect(page.locator("#appShell")).toBeVisible();
  const result = await page.evaluate(async () => {
    const headings = [];
    for (const canonical of [false, true]) {
      const streams = { time: [0, 1, 2], power: [100, 110, 120], velocity: [3, 4, 5] };
      if (canonical) { streams.watts = [200, 210, 220]; streams.velocity_smooth = [6, 7, 8]; }
      const data = { activity: { id: "synthetic-alias", name: "Synthetic alias activity", streams } };
      await ActivityDetails.open(data.activity, { api: async () => data, showDialog: (dialog) => dialog.showModal() });
      headings.push([...document.querySelectorAll(".activity-series h3")].map((node) => node.textContent));
      ActivityDetails.close(false);
    }
    return headings;
  });
  for (const headings of result) {
    expect(headings.filter((heading) => heading.startsWith("Leistung"))).toHaveLength(1);
    expect(headings.filter((heading) => heading.startsWith("Geschwindigkeit"))).toHaveLength(1);
  }
});
