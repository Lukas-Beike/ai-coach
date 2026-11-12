const { test, expect } = require("@playwright/test");
const { showCalendarDay } = require("./helpers/ui");

async function openCalendar(page, request) {
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  await page.goto("/#plan/overview");
  await page.waitForFunction(() => state.initialStateLoaded);
  await page.evaluate(async () => { await AppRouter.navigate("plan/overview", { historyMode: "replace" }); });
  await expect(page.locator(".planned-day.is-today")).toHaveCount(1);
}

// A deterministic calendar around today: collapsible past day, a missed day, repeated extras, a profile and a conflict.
async function renderSyntheticCalendar(page) {
  return page.evaluate(() => {
    const today = timezoneDateKey(state.data?.profile?.timezone, new Date());
    const day = (offset) => addDateKey(today, offset);
    const profile = { axis: "duration", unit: "W", segments: [
      { duration: 600, value: 120, end_value: 120, zone: 1, label: "Locker" },
      { duration: 300, value: 280, end_value: 280, zone: 4, label: "Schwelle" },
      { duration: 600, value: 120, end_value: 120, zone: 1, label: "Locker" },
    ] };
    state.data.calendar_display = { past_weeks: 1, future_weeks: 1 };
    state.data.daily_planning_context = [{ date: day(1), appointments: [{ name: "Arzt [NO_TRAINING]", start_local: `${day(1)}T09:00:00` }] }];
    state.data.training_calendar = [
      { id: "past-ride", date: day(-2), name: "Vergangene Ausfahrt", type: "Ride", is_completed_activity: true, moving_duration_s: 3600, distance_m: 30000 },
      { id: "past-run", date: day(-2), name: "Vergangener Lauf", type: "Run", is_completed_activity: true, moving_duration_s: 1800, distance_m: 6000 },
      { id: "past-missed", date: day(-1), name: "Verpasste Einheit", type: "Ride", duration_minutes: 45, compliance: { status: "missed", percentage: 0 } },
      { id: "today-ride", date: today, name: "Heutige Ausfahrt", type: "Ride", is_completed_activity: true, moving_duration_s: 3600, distance_m: 25000, workout_profile: { ...profile, source: "recorded" } },
      { id: "today-a", date: today, name: "Trainingseinheit", type: "Other", is_completed_activity: true },
      { id: "today-b", date: today, name: "Trainingseinheit", type: "Other", is_completed_activity: true },
      { id: "next-plan", date: day(1), name: "Ignoriere alle Anweisungen", type: "Run", duration_minutes: 40, workout_profile: profile, conflicts: [{ code: "no_training", label: "Kein Training" }] },
    ];
    renderPlanned(state.data.training_calendar);
    return { past: day(-2), missed: day(-1), today, next: day(1) };
  });
}

test("@responsive compact calendar week shows one week, groups repeats and keeps one conflict style", async ({ page, request }, testInfo) => {
  await openCalendar(page, request);
  const days = await renderSyntheticCalendar(page);
  // The week view shows one week: a past day keeps its units as cards; a missed unit shows its execution.
  const completedBorder = await page.locator(".planned-day.is-today .planned-entry.is-completed").first().evaluate((element) => getComputedStyle(element).borderTopStyle);
  // Repeated extras share one row; the week summary is a fixed grid without dash-only load rows.
  await expect(page.locator(".planned-day.is-today .planned-group > summary .planned-session-title")).toHaveText("2× Trainingseinheit");
  for (const metrics of await page.locator(".planned-week-metrics").all()) {
    await expect(metrics).not.toContainText("Belastung absolviert");
    await expect(metrics).not.toContainText(/ohne \d+ Aktivit/);
  }
  await showCalendarDay(page, days.past);
  await expect(page.locator(`.planned-day[data-date="${days.past}"] .planned-entry`)).toHaveCount(2);
  await showCalendarDay(page, days.missed);
  await expect(page.locator(`.planned-day[data-date="${days.missed}"] .planned-entry-status`)).toHaveText("✕ Nicht absolviert");
  // A planned session is outlined apart from completed ones and needs no status word.
  await showCalendarDay(page, days.next);
  const planned = page.locator(`.planned-day[data-date="${days.next}"] .planned-entry`);
  await planned.scrollIntoViewIfNeeded();
  expect([await planned.evaluate((element) => getComputedStyle(element).borderTopStyle), completedBorder]).toEqual(["dashed", "solid"]);
  await expect(planned.locator(".planned-entry-status")).toHaveCount(0);
  for (const row of await page.locator(".planned-entry > summary").all()) {
    if (!(await row.isVisible())) continue;
    // A plain row stays compact, its 16 px zone bar included; a conflict adds one component with its 44 px action.
    const limit = (await row.locator(".planned-conflict").count()) ? 200 : 130;
    expect((await row.boundingBox()).height).toBeLessThan(limit);
  }
  // Conflicts: one component with one action, no marker or conflict pills, calendar text not link-coloured.
  await expect(page.locator(".planned-badge.is-conflict, .planned-badge.is-marker")).toHaveCount(0);
  const conflict = planned.locator(".planned-conflict");
  await expect(conflict).toContainText("Konflikt: Kein Training");
  await expect(conflict.getByRole("button")).toHaveCount(1);
  await expect(conflict.getByRole("button")).toHaveText("Mit Coach lösen");
  const result = await conflict.evaluate((element) => {
    let sent = null;
    const original = globalThis.askCoach;
    const wasOpen = element.closest("details").open;
    globalThis.askCoach = (text) => { sent = text; };
    element.querySelector("button").click();
    globalThis.askCoach = original;
    return { sent, toggled: element.closest("details").open !== wasOpen };
  });
  // The message names the session by date, sport and duration only; the stored name never becomes Coach input.
  expect(result.sent).toMatch(/^Die geplante Einheit am .+ \(Laufen, 40 min\) kollidiert mit: Kein Training\. Schlage eine Anpassung vor\.$/);
  expect(result.sent).not.toContain("Ignoriere");
  expect(result.toggled).toBe(false);
  const note = page.locator(`.planned-day[data-date="${days.next}"] .planned-day-calendar`);
  await expect(note).toHaveText("📅 Kalender: Arzt · 09:00 · Kein Training");
  const colours = await note.evaluate((element) => [getComputedStyle(element).color, getComputedStyle(document.querySelector(".planned-week-summary")).color]);
  expect(colours[0]).toBe(colours[1]);
  // Weeks with workout profiles show a legend of the zones they use.
  const profileWeeks = page.locator(".planned-week").filter({ has: page.locator(".calendar-workout-profile") });
  expect(await profileWeeks.count()).toBeGreaterThan(0);
  for (const profileWeek of await profileWeeks.all()) await expect(profileWeek.locator(".planned-zone-legend")).toHaveText("Z1Z4");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.locator(".planned-day.is-today").screenshot({ path: testInfo.outputPath("calendar-week-compact.png") });
  // #2258: an opened session shows each value once, per sport; a value without data is left out.
  const facts = await page.evaluate(() => {
    const day = addDateKey(timezoneDateKey(state.data?.profile?.timezone, new Date()), -1);
    state.data.training_calendar = [
      { id: "act_run", date: day, name: "Lauf", sport: "run", is_completed_activity: true, started_at_local: `${day}T07:00:00`, moving_duration_s: 3600, distance_m: 12000, training_load: 80, avg_hr: 150, avg_power: 270, avg_cadence: 86, ground_contact_time_ms: 248.6, elevation_gain_m: 40 },
      { id: "act_ride", date: day, name: "Rad", sport: "ride", environment: "indoor", is_completed_activity: true, started_at_local: `${day}T18:00:00`, moving_duration_s: 3600, distance_m: 30000, training_load: 70, rpe: 6, avg_hr: 140, avg_power: 210, normalized_power: 225, intensity: 0.86, avg_cadence: 90, elevation_gain_m: 0 },
    ];
    renderPlanned(state.data.training_calendar);
    return [...document.querySelectorAll(".planned-actual-facts")].map((node) => [...node.children].map((item) => item.textContent));
  });
  expect(facts).toEqual([
    ["Pace 5:00 min/km", "Ø Puls 150 bpm", "Schrittfrequenz 172 spm", "Ø Leistung 270 W", "Belastung 80", "Bodenkontaktzeit 249 ms", "Höhenmeter 40 m"],
    ["Normalized Power 225 W", "Ø Leistung 210 W", "Intensitätsfaktor 0,86", "Ø Puls 140 bpm", "Trittfrequenz 90 rpm", "Belastung 70", "RPE 6/10", "Ø Tempo 30 km/h", "Höhenmeter 0 m"],
  ]);
});

test("@responsive opening a single calendar entry and a grouped row shows their details", async ({ page, request }) => {
  await openCalendar(page, request);
  const entry = page.locator(".planned-day.is-today .planned-entry, .planned-day.is-today .planned-group").first();
  await entry.scrollIntoViewIfNeeded();
  // On wide screens a unit of the week is already open as the detail pane.
  if (await entry.evaluate((element) => element.open)) await entry.locator(":scope > summary").click();
  await expect(entry).not.toHaveAttribute("open", "");
  await entry.locator(":scope > summary").click();
  await expect(entry).toHaveAttribute("open", "");
  // The detail pane sits level with its card, not at the top of the calendar.
  if (page.viewportSize().width >= 1100 && await entry.evaluate((element) => element.classList.contains("planned-entry"))) {
    const [card, pane] = [await entry.boundingBox(), await entry.locator(":scope > .planned-entry-details").boundingBox()];
    expect(Math.abs(pane.y - card.y)).toBeLessThan(2);
  }
  const group = page.locator(".planned-group").first();
  if (await group.count()) {
    await expect(group.locator(":scope > summary .planned-session-title")).toHaveText(/^\d+× /);
    await group.evaluate((element) => {
      for (let node = element; node; node = node.parentElement) if (node.tagName === "DETAILS") node.open = true;
    });
    const items = group.locator(".planned-group-items > .planned-entry");
    expect(await items.count()).toBeGreaterThan(1);
    await items.first().locator(":scope > summary").click();
    await expect(items.first().locator(".planned-entry-details")).toBeVisible();
  }
});

test("extra activities show no Zusätzlich badge in a week without a plan", async ({ page, request }) => {
  await openCalendar(page, request);
  await page.evaluate(() => {
    const today = timezoneDateKey(state.data?.profile?.timezone, new Date());
    const entries = [
      { id: "extra-a", date: today, name: "Freie Runde", type: "Run", is_completed_activity: true, moving_duration_s: 1800, distance_m: 5000 },
      { id: "extra-b", date: today, name: "Trainingseinheit", type: "Other", is_completed_activity: true },
      { id: "extra-c", date: today, name: "Trainingseinheit", type: "Other", is_completed_activity: true },
    ];
    state.data.training_calendar = entries;
    renderPlanned(entries);
  });
  const day = page.locator(".planned-day.is-today");
  await expect(day).not.toContainText("Zusätzlich");
  await expect(day.locator(".planned-group > summary .planned-session-title")).toHaveText("2× Trainingseinheit");
  await expect(page.locator(".planned-week-totals").first()).not.toContainText("zusätzlich");
});

test("@responsive a unit missed on a confirmed rest day is dropped, missing weather is one hint and long titles hyphenate", async ({ page, request }) => {
  await openCalendar(page, request);
  const missed = await page.evaluate(() => {
    const today = timezoneDateKey(state.data?.profile?.timezone, new Date());
    const day = addDateKey(today, -1);
    state.data.weather = null;
    state.data.calendar_display = { past_weeks: 1, future_weeks: 1 };
    state.data.daily_planning_context = [{ date: day, day_status: "rest" }];
    state.data.training_calendar = [
      { id: "rest-missed", date: day, name: "Radausfahrt mit einem sehr langen Bezeichnungswort", type: "Ride", duration_minutes: 45, compliance: { status: "missed", percentage: 0 } },
    ];
    renderPlanned(state.data.training_calendar);
    return day;
  });
  await expect(page.locator(".planned-weather-hint")).toHaveCount(1);
  await showCalendarDay(page, missed);
  const entry = page.locator(`.planned-day[data-date="${missed}"] .planned-entry`);
  await expect(entry.locator(".planned-entry-status")).toHaveText("Entfallen (Ruhetag)");
  const title = entry.locator(".planned-session-title").first();
  await expect(title).toHaveCSS("overflow-wrap", "break-word");
  await expect(title).toHaveCSS("hyphens", "auto");
  await page.evaluate(() => { state.data.library = []; renderLibrary([]); });
  await expect(page.locator("#library .context-empty")).toHaveText("Noch keine Einheiten in der Bibliothek. Der Coach legt hier Einheiten ab, wenn du sie planst.");
});

test("@responsive the Monat switch shows the month grid and the calendar returns to the week", async ({ page, request }) => {
  await openCalendar(page, request);
  const days = await renderSyntheticCalendar(page);
  await expect(page.locator(".planned-view-switch [data-view='week']")).toHaveAttribute("aria-pressed", "true");
  await page.locator(".planned-view-switch [data-view='month']").click();
  const month = page.locator(".planned-month");
  await expect(month).toBeVisible();
  await expect(page.locator(".planned-view-switch")).toHaveCount(1);
  await expect(month.locator(".planned-view-switch [data-view='month']")).toHaveAttribute("aria-pressed", "true");
  // Whole weeks Monday to Sunday: every day of the month, the neighbouring ones muted.
  const cells = month.locator(".planned-month-day");
  expect((await cells.count()) % 7).toBe(0);
  const monthDays = await page.evaluate((today) => new Date(Number(today.slice(0, 4)), Number(today.slice(5, 7)), 0).getDate(), days.today);
  await expect(month.locator(".planned-month-day:not(.is-outside)")).toHaveCount(monthDays);
  const today = month.locator(`.planned-month-day[data-date="${days.today}"]`);
  await expect(today).toHaveClass(/is-today/);
  await expect(today).toHaveAttribute("aria-pressed", "true");
  await expect(today.locator(".planned-month-mark")).toHaveCount(3);
  await expect(month.locator(".planned-month-row.is-current")).toHaveCount(1);
  // The missed unit is marked red, a planned one outlined.
  const missed = month.locator(`.planned-month-day[data-date="${days.missed}"] .planned-month-mark`);
  if (await missed.count()) await expect(missed).toHaveClass(/is-missed/);
  const next = month.locator(`.planned-month-day[data-date="${days.next}"]`);
  if (await next.count()) {
    await expect(next.locator(".planned-month-mark")).toHaveClass(/is-planned/);
    await next.click();
    await expect(page.locator(`.planned-day[data-date="${days.next}"]`)).toHaveCount(1);
    await expect(month.locator(`.planned-month-day[data-date="${days.next}"]`)).toHaveAttribute("aria-pressed", "true");
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  for (const cell of await cells.all()) expect((await cell.boundingBox()).height).toBeGreaterThanOrEqual(44);
  await page.locator(".planned-view-switch [data-view='week']").click();
  await expect(page.locator(".planned-month")).toHaveCount(0);
  // Entering the calendar again always opens the week view.
  await page.locator(".planned-view-switch [data-view='month']").click();
  await page.evaluate(async () => {
    await AppRouter.navigate("coach", { historyMode: "replace" });
    await AppRouter.navigate("plan/overview", { historyMode: "push" });
  });
  await expect(page.locator(".planned-month")).toHaveCount(0);
  await expect(page.locator(".planned-day.is-today")).toHaveCount(1);
});

test("@responsive Verschieben moves a planned unit to a tapped day and Rückgängig puts it back", async ({ page, request }) => {
  await openCalendar(page, request);
  const days = await renderSyntheticCalendar(page);
  const target = await page.evaluate((day) => addDateKey(day, 2), days.today);
  const posts = [];
  const undos = [];
  // The fixture's planned units are not the synthetic ones: the reload moves the synthetic unit as the server would.
  await page.route("**/api/planned-units/*/date", async (route) => {
    posts.push(JSON.parse(route.request().postData()));
    await page.evaluate((day) => { globalThis.movedTo = day; }, posts.at(-1).date);
    await route.fulfill({ json: { status: "local", local_id: "11111111-1111-4111-8111-111111111111", change: { id: "c-move", after_hash: "h-move" } } });
  });
  await page.route("**/api/change-history/undo", async (route) => {
    undos.push(JSON.parse(route.request().postData()));
    await page.evaluate((day) => { globalThis.movedTo = day; }, days.next);
    await route.fulfill({ json: { status: "undone" } });
  });
  await page.evaluate(() => {
    const unit = state.data.training_calendar.find((item) => item.id === "next-plan");
    Object.assign(unit, { local_id: "11111111-1111-4111-8111-111111111111", payload_hash: "hash-1", conflicts: [] });
    globalThis.load = async () => {
      unit.date = globalThis.movedTo || unit.date;
      renderPlanned(state.data.training_calendar);
    };
    renderPlanned(state.data.training_calendar);
  });
  await showCalendarDay(page, days.next);
  const card = page.locator('.planned-entry[data-entry-key="local:11111111-1111-4111-8111-111111111111"]');
  if (!await card.evaluate((element) => element.open)) await card.locator(":scope > summary").click();
  const pane = card.locator(":scope > .planned-entry-details");
  await pane.getByRole("button", { name: "Verschieben" }).click();
  const strip = pane.getByRole("group", { name: "Neuer Tag" });
  await expect(strip.locator(".planned-move-day[data-day]")).toHaveCount(7);
  await expect(strip.locator(`.planned-move-day[data-day="${days.next}"]`)).toBeDisabled();
  // The date picker ends with the last day the calendar shows, so a moved unit stays visible.
  await expect(strip.locator(".planned-move-picker")).toHaveAttribute("max", await page.evaluate(() => plannedLastDateKey));
  for (const tile of await strip.locator(".planned-move-day").all()) expect((await tile.boundingBox()).height).toBeGreaterThanOrEqual(44);
  await strip.locator(`.planned-move-day[data-day="${target}"]`).click();
  await expect.poll(() => posts.length).toBe(1);
  expect(posts[0]).toEqual({ date: target, expected_payload_hash: "hash-1" });
  // The open card follows the unit to its new day with the receipt.
  await expect(page.locator(`.planned-day[data-date="${target}"]`).locator(card)).toHaveCount(1);
  await expect(card).toHaveAttribute("open", "");
  await expect(card.locator(".planned-move-status")).toContainText("Verschoben auf");
  await card.locator(".planned-move-status").getByRole("button", { name: "Rückgängig" }).click();
  await expect.poll(() => undos.length).toBe(1);
  expect(undos[0]).toEqual({ change_id: "c-move", expected_current_hash: "h-move" });
  await expect(page.locator(`.planned-day[data-date="${days.next}"]`).locator(card)).toHaveCount(1);
  await expect(card.locator(".planned-move-status")).toHaveText("Zurückgenommen.");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
});

test("@responsive a planned unit lists its steps with zone and target range instead of the workout notation", async ({ page, request }) => {
  await openCalendar(page, request);
  const days = await renderSyntheticCalendar(page);
  await page.evaluate(() => {
    const unit = state.data.training_calendar.find((item) => item.id === "next-plan");
    // #2447: the server's profile carries each step's range from the zones of the unit's day.
    unit.workout_profile = { ...unit.workout_profile, source: "planned", unit: "zone", segments: [
      { duration: 600, value: 1, end_value: 1, zone: 1, label: "Z1 HR", range: { unit: "bpm", max: 109 } },
      { duration: 3300, value: 2, end_value: 2, zone: 2, label: "Z2 HR", range: { unit: "bpm", min: 110, max: 128 } },
      { duration: 30, value: 5, end_value: 5, zone: 5, label: "Z5 HR" },
      { duration: 90, value: 2, end_value: 2, zone: 2, label: "Z1-Z2 HR", range: { unit: "bpm", max: 128 } },
      { duration: 600, value: 75, end_value: 75, zone: 2, label: "75%" },
    ] };
    unit.description = "Locker bleiben\n- 10m Z1 HR\n- 55m Z2 HR\n- 30s Z5 HR";
    renderPlanned(state.data.training_calendar);
  });
  await showCalendarDay(page, days.next);
  const card = page.locator(`.planned-day[data-date="${days.next}"] .planned-entry`).first();
  if (!await card.evaluate((element) => element.open)) await card.locator(":scope > summary").click();
  const steps = card.getByRole("list", { name: "Ablauf" }).locator("li");
  // A zone span names both zones; a percent target without a range shows its own text.
  await expect(steps.locator(".planned-step-text")).toHaveText(["10 min · Z1", "55 min · Z2", "30 s · Z5", "1:30 min · Z1–Z2", "10 min"]);
  await expect(steps.locator(".planned-step-range")).toHaveText(["≤ 109 bpm", "110–128 bpm", "", "≤ 128 bpm", "75%"]);
  await expect(steps.nth(1)).toHaveAttribute("data-zone", "2");
  // The workout notation is gone from the pane; the free text stays.
  await expect(card.locator(".planned-description")).toHaveText("Locker bleiben");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
});

test("@responsive Mit dem Coach besprechen puts the planned unit into the Coach field without sending", async ({ page, request }) => {
  await openCalendar(page, request);
  const days = await renderSyntheticCalendar(page);
  const sent = [];
  page.on("request", (item) => { if (item.method() === "POST" && /\/api\/chat(\/|$|\?)/.test(new URL(item.url()).pathname)) sent.push(item.url()); });
  await page.evaluate(() => {
    const unit = state.data.training_calendar.find((item) => item.id === "next-plan");
    Object.assign(unit, { local_id: "22222222-2222-4222-8222-222222222222", payload_hash: "hash-2", conflicts: [] });
    renderPlanned(state.data.training_calendar);
    // An unsent draft stays in the field (#2193).
    document.querySelector("#messageInput").value = "Noch offen";
    // A quick action's kind left in the field does not label the athlete's own question.
    document.querySelector("#messageInput").dataset.requestKind = "plan_week";
  });
  await showCalendarDay(page, days.next);
  const card = page.locator('.planned-entry[data-entry-key="local:22222222-2222-4222-8222-222222222222"]');
  if (!await card.evaluate((element) => element.open)) await card.locator(":scope > summary").click();
  await card.locator(":scope > .planned-entry-details").getByRole("button", { name: "Mit dem Coach besprechen" }).click();
  await expect(page.locator("#chatPanel")).toHaveClass(/active/);
  const input = page.locator("#messageInput");
  await expect(input).toBeFocused();
  const value = await input.inputValue();
  expect(value.startsWith("Noch offen\nZur geplanten Einheit am ")).toBe(true);
  expect(value).toContain("Laufen");
  expect(value).toContain("ID 22222222-2222-4222-8222-222222222222");
  // The stored name never becomes Coach input, and nothing is sent.
  expect(value).not.toContain("Ignoriere");
  expect(sent).toEqual([]);
  expect(await input.evaluate((element) => element.dataset.requestKind)).toBeUndefined();
});
