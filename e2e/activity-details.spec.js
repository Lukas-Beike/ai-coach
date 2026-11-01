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
  const rpe = dialog.getByLabel("Session-RPE (0–10)");
  await expect(rpe.locator("option", { hasText: "5 · Schwer" })).toHaveCount(1);
  await rpe.selectOption("6.5");
  await dialog.getByLabel("Abweichungsgrund").fill("Heat");
  await dialog.getByLabel("Notizen").fill("Synthetic feedback");
  await dialog.getByRole("button", { name: "Feedback speichern" }).click();
  await expect(dialog.locator('[role="status"]').filter({ hasText: "Feedback gespeichert" })).toBeVisible();
  await expect(dialog.getByText("Session-RPE-Last: 403 AU · RPE 6,5 (Athletenfeedback) × 62 min")).toBeVisible();
  await dialog.getByRole("button", { name: "Zurück zum Kalender" }).click();
  await page.reload();
  const response = await request.get("/api/activities/FixtureCase-1");
  const payload = await response.json();
  expect(payload.contract).toBe("activity_detail.v1");
  expect(payload.detail_data.display_sampled).toBe(true);
  expect(payload.streams.time_s.length).toBe(2000);
  expect(payload.session.started_at_local).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/);
  expect(payload.activity_feedback.session_rpe).toBe(6.5);
  expect(payload.activity_feedback.notes).toBe("Synthetic feedback");
});


test("@responsive load tab shows the session-RPE load with its coverage", async ({ page }) => {
  await page.goto("/#analysis/load");
  await expect(page.locator("#appShell")).toBeVisible();
  const heading = page.locator("#analysisLoadCharts").getByRole("heading", { name: /^Session-RPE-Last · \d+\/\d+ bewertet/ });
  await expect(heading).toBeVisible();
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

test("@responsive activity details chart each document channel once", async ({ page }) => {
  await page.goto("/#plan/overview");
  await expect(page.locator("#appShell")).toBeVisible();
  const headings = await page.evaluate(async () => {
    const channel = (values) => ({ values, source: { label: "Intervals.icu" }, aligned: true });
    const data = {
      contract: "activity_detail.v1",
      session: { activity_id: "act_channels", name: "Synthetic channel activity", sport: "ride" },
      streams: { time_s: [0, 1, 2], channels: { power_w: channel([200, 210, 220]), speed_mps: channel([6, 7, 8]), moving: channel([1, 1, 1]) } },
      detail_data: { providers: [] },
    };
    await ActivityDetails.open({ id: "act_channels" }, { api: async () => data, showDialog: (dialog) => dialog.showModal() });
    const result = [...document.querySelectorAll(".activity-series h3")].map((node) => node.textContent);
    ActivityDetails.close(false);
    return result;
  });
  expect(headings).toEqual(["Leistung (W)", "Geschwindigkeit (m/s)"]);
});

test("@responsive Garmin-only session shows per-provider notes and its own refresh", async ({ page }) => {
  await page.goto("/#plan/overview");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.evaluate(async () => {
    const entry = (provider, label, fields) => ({ provider, label, kinds: ["streams"], fetched_at: "2026-10-17T09:00:00Z", refreshable: false, stale: false, load_error: null, coverage: {}, ...fields });
    const data = {
      contract: "activity_detail.v1",
      session: { activity_id: "act_garmin", name: "Synthetic Garmin ride <img src=x>", sport: "ride", started_at: "2026-10-17T06:00:00+00:00" },
      metrics: { duration_s: { value: 3600, unit: "s" } },
      streams: { time_s: [0, 60, 120], channels: { power_w: { values: [180, 190, 200], source: { label: "Garmin Connect" }, aligned: true } } },
      laps: null,
      zones: {},
      analysis: null,
      detail_data: {
        providers: [
          entry("garmin", "Garmin Connect", { refreshable: true, stale: true, load_error: { message: "Garmin Connect lieferte keine Runden.", observed_at: "2026-10-17T09:30:00Z" }, coverage: { power_w: { points: 3, valid_points: 3 } } }),
          entry("wahoo", "Wahoo", { load_error: { message: "Wahoo-Datei unvollständig.", observed_at: "2026-10-17T09:40:00Z" } }),
        ],
        display_sampled: false,
      },
      activity_feedback: null,
      equipment: [],
    };
    globalThis.syntheticCalls = [];
    const fakeApi = async (url, options) => {
      syntheticCalls.push({ url, body: options?.body ? JSON.parse(options.body) : null });
      if (url === "/api/sync/jobs") return { id: "synthetic-job", status: "completed" };
      return data;
    };
    await ActivityDetails.open({ id: "act_garmin" }, { api: fakeApi, showDialog: (dialog) => dialog.showModal() });
  });
  const dialog = page.getByRole("dialog", { name: "Synthetic Garmin ride <img src=x>" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("img", { name: "Leistung, Zeitachse in Minuten" })).toBeVisible();
  await expect(dialog.getByText("Garmin Connect: Die Zusammenfassung hat sich seit dem Laden geändert.", { exact: false })).toBeVisible();
  await expect(dialog.locator(".activity-analysis-error").filter({ hasText: "Garmin Connect: Garmin Connect lieferte keine Runden." })).toBeVisible();
  await expect(dialog.locator(".activity-analysis-error").filter({ hasText: "Wahoo: Wahoo-Datei unvollständig." })).toBeVisible();
  await expect(dialog.getByText("Datenabdeckung Garmin Connect · power_w: 3/3 Messwerte")).toBeVisible();
  await expect(dialog.getByRole("button", { name: /Wahoo/ })).toHaveCount(0);
  await dialog.getByRole("button", { name: "Garmin Connect: Detaildaten aktualisieren" }).click();
  await expect.poll(() => page.evaluate(() => syntheticCalls.filter((call) => call.url === "/api/activities/act_garmin").length)).toBe(2);
  const job = await page.evaluate(() => syntheticCalls.find((call) => call.url === "/api/sync/jobs").body);
  expect(job).toEqual({ provider: "garmin", type: "activity_details", payload: { activity_id: "act_garmin" } });
  expect(await dialog.locator("img").count()).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.evaluate(() => ActivityDetails.close(false));
});

test("@responsive running cadence shows step frequency of both legs", async ({ page }) => {
  await page.goto("/#plan/overview");
  await expect(page.locator("#appShell")).toBeVisible();
  const headings = await page.evaluate(async () => {
    const result = {};
    for (const type of ["Run", "Ride"]) {
      const data = { session: { activity_id: `synthetic-${type}`, name: `Synthetic ${type}`, sport: type.toLowerCase() }, streams: { time_s: [0, 1, 2], channels: { cadence_rpm: { values: [86, 88, 90] } } }, detail_data: { providers: [] } };
      await ActivityDetails.open({ id: `synthetic-${type}` }, { api: async () => data, showDialog: (dialog) => dialog.showModal() });
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
    { id: "synthetic-run", name: "Synthetic run", type: "Run", started_at_local: "2026-10-17T08:00:00", moving_duration_s: 3 },
    { id: "synthetic-ride", name: "Synthetic ride cadence", type: "Ride", started_at_local: "2026-10-16T08:00:00", moving_duration_s: 3 },
  ];
  await page.route(/\/api\/activities(\?|\/)/, (route) => {
    const id = new URL(route.request().url()).pathname.split("/")[3];
    const body = id
      ? {
        session: { activity_id: id, sport: id === "synthetic-run" ? "run" : "ride" },
        metrics: { avg_cadence: { value: 86 }, max_cadence: { value: 90 } },
        streams: { time_s: [0, 1, 2], channels: { cadence_rpm: { values: [84, 86, 90] } } },
        detail_data: { providers: [] },
      }
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

test("@responsive analysis lists sessions whose details failed to load", async ({ page }) => {
  const message = "Intervals.icu hat für diese Einheit keine Detaildaten geliefert.";
  const summaries = [
    { id: "synthetic-failed", name: "Synthetic failed <img src=x>", type: "Ride", started_at_local: "2026-10-17T08:00:00", moving_duration_s: 3, detail_error: message },
  ];
  await page.route(/\/api\/activities(\?|\/)/, (route) => {
    const id = new URL(route.request().url()).pathname.split("/")[3];
    const body = id
      ? { session: { activity_id: id, sport: "ride" }, metrics: {}, detail_data: { providers: [{ provider: "intervals", label: "Intervals.icu", kinds: [], fetched_at: null, refreshable: true, stale: false, load_error: { message, observed_at: "2026-10-17T09:00:00Z" }, coverage: {} }] } }
      : { activities: summaries, snapshot_synced_at: "2026-10-17T09:00:00Z", next_cursor: null };
    return route.fulfill({ json: body });
  });
  await page.goto("/#analysis/sessions");
  await expect(page.locator("#appShell")).toBeVisible();
  const item = page.locator(".activity-analysis-item").filter({ hasText: "Synthetic failed <img src=x>" });
  const flag = item.locator("summary > .activity-analysis-error");
  await expect(flag).toHaveText("Details nicht geladen");
  await expect(flag).toHaveAttribute("title", message);
  await item.locator("summary").click();
  await expect(item.locator(".activity-analysis-panel .activity-analysis-error")).toContainText(message);
  expect(await item.locator("img").count()).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
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
