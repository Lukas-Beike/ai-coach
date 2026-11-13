const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;
const { showCalendarDay } = require("./helpers/ui");
const { openCalendar } = require("./helpers/calendar");

// Fake personal events around tomorrow: one per impact, a weekly series and a title marker.
async function renderEvents(page) {
  return page.evaluate(() => {
    const today = timezoneDateKey(state.data?.profile?.timezone, new Date());
    const day = addDateKey(today, 1);
    const week = addDateKey(today, 8);
    const event = (uid, start, end, impact, extra = {}) => ({
      uid, name: uid, start_local: `${start}`, end_local: `${end}`, event_date: start.slice(0, 10), all_day: 0,
      impact, decision_scope: impact === "open" ? null : "event", recurring: 0, ...extra,
    });
    state.data.calendar_display = { past_weeks: 0, future_weeks: 2 };
    state.data.daily_planning_context = [{ date: day, appointments: [{ name: "Teammeeting", start_local: `${day}T08:00:00` }] }];
    state.data.external_calendar = { ...(state.data.external_calendar || {}), events: [
      event("Teammeeting", `${day}T08:00:00`, `${day}T09:00:00`, "none", { recurring: 1, decision_scope: "series" }),
      event("Teammeeting", `${week}T08:00:00`, `${week}T09:00:00`, "none", { recurring: 1, decision_scope: "series" }),
      event("Elternabend <img src=x onerror=alert(1)>", `${day}T19:00:00`, `${day}T21:00:00`, "open"),
      event("Zahnarzt [SHORT_ONLY]", `${day}T07:30:00`, `${day}T08:15:00`, "short", { decision_scope: null }),
      event("Firmenfeier", `${day}T18:00:00`, `${day}T22:00:00`, "easy"),
      event("Dienstreise", `${day}T00:00:00`, `${addDateKey(day, 2)}T00:00:00`, "block", { all_day: 1 }),
      event("Urlaub", `${addDateKey(today, -3)}T00:00:00`, `${addDateKey(today, 1)}T00:00:00`, "none", { all_day: 1 }),
    ] };
    state.data.training_calendar = [{ id: "event-day-run", date: day, name: "Lockerer Dauerlauf", type: "Run", duration_minutes: 45 }];
    renderPlanned(state.data.training_calendar);
    return { day, week, after: addDateKey(day, 1), today };
  });
}

test("@responsive personal events show as a band and take a decision per event or series", async ({ page, request }, testInfo) => {
  await openCalendar(page, request);
  const days = await renderEvents(page);
  await showCalendarDay(page, days.day);
  const band = page.locator(`.planned-day[data-date="${days.day}"] .planned-event-band`);
  const chips = band.locator(".planned-event-chip");
  await expect(chips).toHaveCount(5);
  await expect(band.locator("img")).toHaveCount(0);
  await expect(chips.filter({ hasText: "Zahnarzt" })).toHaveAttribute("data-impact", "short");
  await expect(chips.filter({ hasText: "Zahnarzt" })).not.toContainText("SHORT_ONLY");
  await expect(chips.filter({ hasText: "Dienstreise" })).toContainText("ganztägig");
  // An event that began before today shows from today on only.
  expect(await page.evaluate((today) => [...plannedEventsByDate(today).keys()].every((day) => day >= today), days.today)).toBe(true);
  // A multi-day event shows on each of its days but not on its end day at midnight.
  await expect(page.locator(`.planned-day[data-date="${days.after}"] .planned-event-chip`)).toHaveCount(1);
  // The band replaces the calendar note line for the day.
  await expect(page.locator(`.planned-day[data-date="${days.day}"] .planned-day-calendar`)).toHaveCount(0);
  const open = chips.filter({ hasText: "Elternabend" });
  await expect(open).toHaveAttribute("data-impact", "open");
  await expect(open).toHaveAccessibleName(/Elternabend .*19:00–21:00, Offen/);

  const posts = [];
  await page.route("**/api/external-calendar/decisions", async (route) => {
    posts.push(route.request().postDataJSON());
    await route.fulfill({ json: { needs_replan: false, replan_changes: 0 } });
  });
  // One event: no scope switch for a single occurrence; the chip takes the decision.
  await open.focus();
  await page.keyboard.press("Enter");
  const sheet = page.locator(".planned-event-sheet");
  await expect(sheet).toBeVisible();
  await page.locator(`.planned-day[data-date="${days.day}"]`).screenshot({ path: testInfo.outputPath("event-band-day.png") });
  await page.screenshot({ path: testInfo.outputPath("event-sheet.png"), animations: "disabled" });
  await expect(sheet.getByRole("heading")).toContainText("Elternabend");
  await expect(sheet.locator(".planned-event-scope")).toHaveCount(0);
  // A tap on the panel's own padding keeps it open.
  await sheet.click({ position: { x: 4, y: 4 } });
  await expect(sheet).toBeVisible();
  await expect(sheet).not.toContainText("null");
  await sheet.getByRole("button", { name: "Kürzer" }).click();
  await expect(sheet).toHaveCount(0);
  expect(posts.at(-1)).toEqual({ uid: "Elternabend <img src=x onerror=alert(1)>", occurrence_start: `${days.day}T19:00:00`, impact: "short" });
  const decided = page.locator(`.planned-day[data-date="${days.day}"] .planned-event-chip`).filter({ hasText: "Elternabend" });
  await expect(decided).toHaveAttribute("data-impact", "short");
  await expect(decided).toBeFocused();

  // A series: the scope switch starts on every occurrence and the decision reaches the next week too.
  await page.locator(`.planned-day[data-date="${days.day}"] .planned-event-chip`).filter({ hasText: "Teammeeting" }).click();
  await expect(sheet.getByRole("button", { name: "Alle Wiederholungen" })).toHaveAttribute("aria-pressed", "true");
  await expect(sheet.getByRole("button", { name: "Egal" })).toHaveAttribute("aria-pressed", "true");
  await sheet.getByRole("button", { name: "Blockiert" }).click();
  await expect(sheet).toHaveCount(0);
  expect(posts.at(-1)).toEqual({ uid: "Teammeeting", occurrence_start: null, impact: "block" });
  expect(await page.evaluate(() => state.data.external_calendar.events.filter((item) => item.uid === "Teammeeting").map((item) => item.impact))).toEqual(["block", "block"]);

  // Escape closes without a decision; the only-this-occurrence scope sends the start.
  await page.locator(`.planned-day[data-date="${days.day}"] .planned-event-chip`).filter({ hasText: "Teammeeting" }).click();
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  await page.locator(`.planned-day[data-date="${days.day}"] .planned-event-chip`).filter({ hasText: "Teammeeting" }).click();
  await sheet.getByRole("button", { name: "Nur dieser Termin" }).click();
  await sheet.getByRole("button", { name: "Locker" }).click();
  await expect(sheet).toHaveCount(0);
  expect(posts.at(-1)).toEqual({ uid: "Teammeeting", occurrence_start: `${days.day}T08:00:00`, impact: "easy" });
  expect(posts).toHaveLength(3);

  // A failed save keeps the sheet open with the server's message; Escape waits for the answer.
  await page.unroute("**/api/external-calendar/decisions");
  let answer;
  const answered = new Promise((resolve) => { answer = resolve; });
  await page.route("**/api/external-calendar/decisions", async (route) => {
    await answered;
    await route.fulfill({ status: 404, json: { error: "Termin nicht gefunden." } });
  });
  await page.locator(`.planned-day[data-date="${days.day}"] .planned-event-chip`).filter({ hasText: "Firmenfeier" }).click();
  await sheet.getByRole("button", { name: "Egal" }).click();
  await page.keyboard.press("Escape");
  await expect(sheet).toBeVisible();
  answer();
  await expect(sheet.getByRole("status")).toContainText("Termin nicht gefunden.");
  await page.keyboard.press("Escape");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("@responsive event band, notice and sheet meet AA contrast in both themes", async ({ page, request }, testInfo) => {
  await openCalendar(page, request);
  const days = await renderEvents(page);
  await page.evaluate(() => {
    state.data.external_calendar.undecided_upcoming = 1;
    renderPlanned(state.data.training_calendar);
    renderExternalCalendar(state.data);
  });
  await page.locator(".planned-undecided-banner").screenshot({ path: testInfo.outputPath("undecided-banner.png") });
  await showCalendarDay(page, days.day);
  for (const theme of ["dark", "light"]) {
    await page.evaluate((selected) => { document.documentElement.dataset.theme = selected; }, theme);
    const band = await new AxeBuilder({ page }).include(".planned-event-band").include(".planned-undecided-banner").include('.nav-item[data-route="plan"]').withRules(["color-contrast"]).analyze();
    expect(band.violations).toEqual([]);
    await page.locator(".planned-event-chip").first().click();
    const sheet = await new AxeBuilder({ page }).include(".planned-event-sheet").withRules(["color-contrast"]).analyze();
    expect(sheet.violations).toEqual([]);
    await page.keyboard.press("Escape");
  }
});

test("a blocked event marks its day in the month view", async ({ page, request }) => {
  await openCalendar(page, request);
  const days = await renderEvents(page);
  await page.locator(".planned-view-switch [data-view='month']").click();
  const cell = page.locator(`.planned-month-day[data-date="${days.day}"]`);
  await expect(cell).toHaveClass(/has-blocked-event/);
  await expect(cell).toHaveAccessibleName(/Termin blockiert Training/);
  await expect(page.locator(`.planned-month-day[data-date="${addDays(days.day, -1)}"]`)).not.toHaveClass(/has-blocked-event/);
});

function addDays(key, offset) {
  const date = new Date(`${key}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
}

test("@responsive the notice walks through undecided events of the next 14 days and then goes away", async ({ page, request }, testInfo) => {
  await openCalendar(page, request);
  const today = await page.evaluate(() => {
    const date = timezoneDateKey(state.data?.profile?.timezone, new Date());
    const open = (uid, offset) => ({ uid, name: uid, start_local: `${addDateKey(date, offset)}T19:00:00`, end_local: `${addDateKey(date, offset)}T20:00:00`, all_day: 0, impact: "open", decision_scope: null, recurring: 0 });
    state.data.calendar_display = { past_weeks: 0, future_weeks: 3 };
    state.data.external_calendar = { ...(state.data.external_calendar || {}), undecided_upcoming: 2, events: [
      open("Elternabend", 2), open("Dienstreise", 5), open("Später", 20),
      { ...open("Teammeeting", 3), impact: "none", decision_scope: "series", recurring: 1 },
    ] };
    renderPlanned(state.data.training_calendar || []);
    renderExternalCalendar(state.data);
    return date;
  });
  const until = await page.evaluate((date) => new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit" }).format(dateFromKey(addDateKey(date, 14))), today);
  const banner = page.locator(".planned-undecided-banner");
  await expect(banner).toContainText(`2 neue Termine bis ${until}`);
  const nav = page.locator('.nav-item[data-route="plan"]').filter({ visible: true });
  await expect(nav.locator("b.nav-count")).toHaveText("2");
  await expect(nav.locator("b.nav-count")).toBeVisible();
  await nav.screenshot({ path: testInfo.outputPath("nav-count.png") });
  await expect(nav).toHaveAccessibleName(`Kalender, 2 neue Termine bis ${until}`);

  const posts = [];
  await page.route("**/api/external-calendar/decisions", async (route) => {
    posts.push(route.request().postDataJSON());
    await route.fulfill({ json: { undecided_upcoming: 2 - posts.length, needs_replan: false, replan_changes: 0 } });
  });
  await banner.getByRole("button", { name: "Einordnen" }).click();
  const sheet = page.locator(".planned-event-sheet");
  await expect(sheet.getByRole("heading")).toHaveText("Elternabend");
  await sheet.getByRole("button", { name: "Egal" }).click();
  // The next undecided event follows; "Egal" counts as decided.
  await expect(sheet.getByRole("heading")).toHaveText("Dienstreise");
  await expect(banner).toContainText(`1 neuer Termin bis ${until}`);
  await expect(nav.locator("b.nav-count")).toHaveText("1");
  await sheet.getByRole("button", { name: "Blockiert" }).click();
  await expect(sheet).toHaveCount(0);
  await expect(banner).toHaveCount(0);
  await expect(nav.locator("b.nav-count")).toHaveText("");
  await expect(nav).toHaveAccessibleName("Kalender");
  expect(posts.map((post) => [post.uid, post.impact])).toEqual([["Elternabend", "none"], ["Dienstreise", "block"]]);

  // A refresh that brings another occurrence of a decided series does not show the notice again.
  await page.evaluate((date) => {
    state.data.external_calendar = { ...state.data.external_calendar, undecided_upcoming: 0, events: [
      ...state.data.external_calendar.events,
      { uid: "Teammeeting", name: "Teammeeting", start_local: `${addDateKey(date, 10)}T08:00:00`, end_local: `${addDateKey(date, 10)}T09:00:00`, impact: "none", decision_scope: "series", recurring: 1 },
    ] };
    renderPlanned(state.data.training_calendar || []);
    renderExternalCalendar(state.data);
  }, today);
  await expect(banner).toHaveCount(0);
  await expect(nav.locator("b.nav-count")).toHaveText("");
});
