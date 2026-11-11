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
  await expect(page.locator(`.planned-day[data-date="${days.missed}"] .planned-execution`)).toBeVisible();
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
