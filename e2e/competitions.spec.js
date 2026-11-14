const { test, expect } = require("@playwright/test");

async function overview(page) {
  const reads = [], writes = [];
  let fail = false, events;
  await page.route("**/api/bootstrap**", async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    return route.fulfill({ json: events ? { ...data, competitions: events } : data });
  });
  page.on("request", (request) => {
    if (request.url().includes("/api/analysis/season") || request.url().includes("/api/analysis/scenarios")) reads.push(request.url());
    if (/POST|PUT|DELETE|PATCH/.test(request.method()) && request.url().includes("/api/")) writes.push(new URL(request.url()).pathname);
  });
  await page.route("**/api/profile", async (route) => {
    if (fail) return route.fulfill({ status: 503, json: { error: "Synthetic read failure" } });
    const response = await route.fetch();
    const data = await response.json();
    return route.fulfill({ json: { ...data, competitions: events } });
  });
  const racePlans = [];
  await page.route("**/api/competitions/*/race-plan", (route) => {
    racePlans.push(new URL(route.request().url()).pathname);
    return route.fulfill({ json: { ok: true, race_plan: {
      pacing: { status: "ready", method: "equal_effort", profile_rejected: false, sections: [
        { from_km: 0, to_km: 10, grade_pct: 0, pace_s_per_km: 330, time_s: 3300 },
        { from_km: 10, to_km: 12.5, grade_pct: 4, pace_s_per_km: 408, time_s: 1020 },
      ] },
      carbohydrates: { source: "Thomas, Erdman und Burke 2016", weight: { kg: 70, source: "Profil" }, during: { step: "moderate", low_g: 30, high_g: 60 }, before: [
        { kind: "daily", days_before: 1, g_per_kg: [7, 12], grams: [490, 840] },
        { kind: "meal", hours_before: [4, 1], g_per_kg: [1, 4], grams: [70, 280] },
      ] },
    } } });
  });
  // Use the athlete-local day supplied by the disposable fixture.
  await page.goto("/#coach");
  await expect.poll(() => page.evaluate(() => !state.loadPromise && Boolean(state.data?.profile))).toBe(true);
  const today = await page.evaluate(() => todayIso());
  events = [
    { id: "b", name: "Beta", event_date: today, sport: "run", priority: "B", distance: null },
    { id: "a", name: "Alpha mit einem sehr langen Wettkampfnamen für schmale Bildschirme", event_date: today, sport: "other", sport_detail: "Swimrun", priority: "A", distance: "Sprintdistanz", target: "Ankommen", notes: "<img src=x onerror=alert(1)>", sync_state: "local_override", starts_at_local: `${today}T08:30:00`, planned_duration_s: 3600 },
    { id: "old", name: "Alt", event_date: "2020-01-02", sport: "ride", priority: "C", distance: 0 },
    { id: "older", name: "Älter", event_date: "2020-01-01", sport: "run", priority: "B", distance: 5000 },
    { id: "undated", name: "Ohne Datum", event_date: "2026-02-30", sport: "run", priority: "B" },
  ];
  await page.evaluate(async () => { await load("/api/bootstrap?local=1", ["profile"]); await AppRouter.navigate("plan/season"); });
  await expect(page.locator("#competitionList > .competition-card")).toHaveCount(3);
  return { reads, writes, racePlans, setEvents(value) { events = value; }, fail(value) { fail = value; } };
}

test("@responsive competition summaries, saved details and archive stay compact and safe", async ({ page }) => {
  const tracked = await overview(page);
  const root = page.locator("#seasonPreparation");
  await expect(page.getByRole("link", { name: "Wettkämpfe", exact: true })).toHaveAttribute("href", "#plan/season");
  await expect(root.getByRole("heading", { name: "Wettkämpfe", exact: true })).toBeVisible();
  await expect(root.locator(".competition-card[open]")).toHaveCount(0);
  const alpha = root.locator('[data-competition-id="a"]');
  const beta = root.locator('[data-competition-id="b"]');
  await expect(root.locator("#competitionList > .competition-card").first()).toHaveAttribute("data-competition-id", "a");
  await expect(alpha.locator("summary")).toContainText("Swimrun · Sprintdistanz · Priorität A · Heute");
  await expect(beta.locator("summary")).toContainText("Distanz unbekannt");
  await alpha.locator("summary").click();
  await expect(alpha).toContainText("08:30");
  await expect(alpha).toContainText("1:00 h");
  await expect(alpha).toContainText("Lokal geändert");
  await expect(alpha).toContainText("<img src=x onerror=alert(1)>");
  await expect(alpha.locator("img")).toHaveCount(0);
  const plan = alpha.locator(".race-plan");
  await expect(plan).toContainText("gleiche Anstrengung");
  await expect(plan.locator("tbody tr").nth(1)).toHaveText(/km 10–12,5\s*\+4 %\s*6:48\/km\s*17:00/);
  await expect(plan).toContainText("490–840 g/Tag");
  await expect(plan).toContainText("04:30–07:30");
  await expect(plan).toContainText("30–60 g/h");
  expect(tracked.racePlans).toEqual(["/api/competitions/a/race-plan"]);
  await expect(beta).not.toHaveAttribute("open", "");
  const archive = root.locator(".competition-archive");
  await expect(archive).not.toHaveAttribute("open", "");
  await archive.locator(":scope > summary").click();
  await expect(archive.locator(".competition-card").first()).toHaveAttribute("data-competition-id", "old");
  await expect(archive.locator("summary").filter({ hasText: "Alt" }).first()).toContainText("0 km");
  await expect(archive.locator(".race-plan")).toHaveCount(0);
  await expect(root.locator("svg, form, .season-evidence")).toHaveCount(0);
  await expect(root).not.toContainText(/Wochenumfang|Szenarien vergleichen|Zieldistanzvergleich|Taper/);
  for (const theme of ["dark", "light"]) {
    await page.evaluate((theme) => { document.documentElement.dataset.theme = theme; document.documentElement.style.fontSize = "200%"; }, theme);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.evaluate(() => { document.documentElement.style.fontSize = ""; });
  await alpha.locator("summary").focus();
  await page.keyboard.press("Enter");
  await expect(alpha).not.toHaveAttribute("open", "");
  expect(tracked.reads).toEqual([]);
  expect(tracked.writes).toEqual([]);
});

test("@responsive failed reads retain event facts and retry shows saved Coach edits", async ({ page }) => {
  const tracked = await overview(page);
  const alpha = page.locator('[data-competition-id="a"]');
  await alpha.locator("summary").click();
  tracked.fail(true);
  await page.evaluate(async () => { await load("/api/bootstrap?local=1", ["profile"]); });
  await expect(page.locator("#competitionReadStatus")).toContainText("Gespeicherter Stand. Aktualisierung fehlgeschlagen.");
  await expect(alpha).toHaveAttribute("open", "");
  // The Coach's successful save reloads canonical profile state through the same load path.
  tracked.setEvents([{ id: "a", name: "Coach-edited target", event_date: await page.evaluate(() => todayIso()), sport: "run", priority: "C", distance: 10000, target: "55 min", sync_state: "local_override" }]);
  tracked.fail(false);
  await page.locator("#competitionRetry").click();
  await expect(alpha).toContainText("Coach-edited target");
  await expect(alpha).toContainText("55 min");
  await expect(alpha).toHaveAttribute("open", "");
  await expect(page.locator("#competitionReadStatus")).toBeEmpty();
  await expect(page.locator("#competitionRetry")).toBeHidden();
  tracked.setEvents([]);
  await page.evaluate(async () => { await load("/api/bootstrap?local=1", ["profile"]); });
  await expect(page.locator("#competitionList")).toHaveText("Noch keine Wettkämpfe gespeichert.");
  expect(tracked.reads).toEqual([]);
  expect(tracked.writes).toEqual([]);
});

test("@responsive past-only lists keep their archive and equal-date name order", async ({ page }) => {
  const tracked = await overview(page);
  tracked.setEvents([
    { id: "z", name: "Zulu", event_date: "2020-01-02", priority: "A", sport: "run" },
    { id: "a", name: "Alpha", event_date: "2020-01-02", priority: "A", sport: "run" },
  ]);
  await page.evaluate(async () => { await load("/api/bootstrap?local=1", ["profile"]); });
  await expect(page.locator("#competitionList > .competition-card")).toHaveCount(0);
  const archive = page.locator(".competition-archive");
  await expect(archive).not.toHaveAttribute("open", "");
  await archive.locator(":scope > summary").click();
  await expect(archive.locator(".competition-card").first()).toHaveAttribute("data-competition-id", "a");
});

test("initial read failures offer retry without claiming an empty competition list", async ({ page }) => {
  await page.route("**/api/bootstrap**", (route) => route.fulfill({ status: 503, json: { error: "Synthetic startup failure" } }));
  await page.route("**/api/profile", (route) => route.fulfill({ status: 503, json: { error: "Synthetic read failure" } }));
  await page.goto("/#plan/season");
  await expect(page.locator("#competitionReadStatus")).toHaveText("Wettkämpfe konnten nicht geladen werden.");
  await expect(page.locator("#competitionRetry")).toBeVisible();
  await expect(page.locator("#competitionList")).toBeEmpty();
});
