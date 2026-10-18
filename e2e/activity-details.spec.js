const { test, expect } = require("@playwright/test");

test("@responsive activity details preserve calendar without Coach shortcuts", async ({ page, request }) => {
  const seed = await request.get("/api/fixture/activity");
  expect(seed.ok()).toBeTruthy();
  await page.goto("/#plan/overview");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.evaluate(async () => { await AppRouter.navigate("plan/overview", { historyMode: "replace" }); });
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

test("@responsive running cadence shows step frequency of both legs", async ({ page }) => {
  await page.goto("/#plan/overview");
  await expect(page.locator("#appShell")).toBeVisible();
  const headings = await page.evaluate(async () => {
    const result = {};
    for (const type of ["Run", "Ride"]) {
      const data = { activity: { id: `synthetic-${type}`, name: `Synthetic ${type}`, type, streams: { time: [0, 1, 2], cadence: [86, 88, 90] } } };
      await ActivityDetails.open(data.activity, { api: async () => data, showDialog: (dialog) => dialog.showModal() });
      result[type] = [...document.querySelectorAll(".activity-series")].map((node) => node.textContent);
      ActivityDetails.close(false);
    }
    return result;
  });
  expect(headings.Run.find((text) => text.startsWith("Schrittfrequenz (spm)"))).toContain("180");
  expect(headings.Ride.find((text) => text.startsWith("Kadenz (rpm)"))).toContain("90");
});

test("@responsive analysis shows running step frequency and cycling cadence", async ({ page }) => {
  const summaries = [
    { id: "synthetic-run", name: "Synthetic run", type: "Run", start_date_local: "2026-10-17T08:00:00", moving_time: 3, average_cadence: 86, max_cadence: 90 },
    { id: "synthetic-ride", name: "Synthetic ride cadence", type: "Ride", start_date_local: "2026-10-16T08:00:00", moving_time: 3, average_cadence: 86, max_cadence: 90 },
  ];
  await page.route(/\/api\/activities(\?|\/)/, (route) => {
    const id = new URL(route.request().url()).pathname.split("/")[3];
    const body = id
      ? { activity: { id, streams: { time: [0, 1, 2], cadence: [84, 86, 90] } }, detail_data: {} }
      : { activities: summaries, snapshot_synced_at: "2026-10-17T09:00:00Z", next_cursor: null };
    return route.fulfill({ json: body });
  });
  await page.goto("/#analysis/sessions");
  await expect(page.locator("#appShell")).toBeVisible();
  const run = page.locator(".activity-analysis-item").filter({ hasText: "Synthetic run" });
  await run.locator("summary").click();
  await expect(run.locator(".activity-analysis-stats div").filter({ hasText: "Ø Schrittfrequenz" })).toContainText("172 spm");
  await expect(run.getByRole("img", { name: /^Schrittfrequenz: Ø 172/ })).toBeVisible();
  const ride = page.locator(".activity-analysis-item").filter({ hasText: "Synthetic ride cadence" });
  await ride.locator("summary").click();
  await expect(ride.locator(".activity-analysis-stats div").filter({ hasText: "Ø Kadenz" })).toContainText("86 rpm");
  await expect(ride.getByRole("img", { name: /^Kadenz: Ø 86/ })).toBeVisible();
});

test("@responsive analysis sessions list expands Garmin-style charts", async ({ page, request }) => {
  const seed = await request.get("/api/fixture/activity");
  expect(seed.ok()).toBeTruthy();
  await page.goto("/#analysis/sessions");
  await expect(page.locator("#appShell")).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Analysebereiche" });
  await expect(nav.getByRole("link", { name: "Einheiten" })).toHaveAttribute("aria-current", "page");
  await expect(page.locator("#sessionPerformance")).toBeHidden();
  const item = page.locator(".activity-analysis-item").filter({ hasText: "Synthetic ride <img src=x>" }).first();
  await item.locator("summary").click();
  await expect(item.locator(".activity-analysis-stats")).toContainText("25,0 km");
  await expect(item.locator(".activity-analysis-stats div").filter({ hasText: "Intensität" })).toContainText("78 %");
  await expect(item.locator(".activity-analysis-stats div").filter({ hasText: "Normalized Power" })).toContainText("205 W");
  const power = item.getByRole("img", { name: /^Leistung: Ø 200/ });
  await expect(power).toBeVisible();
  await expect(item.getByRole("img", { name: /^Herzfrequenz: Ø 140/ })).toBeVisible();
  const box = await power.boundingBox();
  await power.dispatchEvent("pointerdown", { clientX: box.x + box.width * 0.6, clientY: box.y + box.height / 2 });
  await expect(item.locator(".is-power .activity-analysis-readout")).toContainText("200 W");
  await expect(item.locator(".activity-analysis-zones").filter({ hasText: "Zeit in HF-Zonen" })).toContainText("Z2");
  const temperatureTicks = await item.locator(".is-temperature svg text").allTextContents();
  expect(temperatureTicks.some((text) => /^[-\u2212]\d/.test(text))).toBeTruthy();
  await expect(item).toContainText("Datenabdeckung");
  expect(await item.locator("img").count()).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  for (const link of await nav.getByRole("link").all()) {
    expect(await link.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBeTruthy();
  }
});
