const { test, expect } = require("@playwright/test");

async function openCalendar(page, request) {
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  await page.goto("/#plan/overview");
  await page.waitForFunction(() => state.initialStateLoaded);
  await page.evaluate(async () => { await AppRouter.navigate("plan/overview", { historyMode: "replace" }); });
  await expect(page.locator(".planned-day.is-today")).toHaveCount(1);
}

// Three future endurance units on one day: already sent, never sent, and changed since it was sent.
async function renderUnits(page) {
  return page.evaluate(() => {
    const today = timezoneDateKey(state.data?.profile?.timezone, new Date());
    const date = addDateKey(today, 1);
    const profile = { axis: "duration", unit: "W", segments: [
      { duration: 900, value: 120, end_value: 120, zone: 1, label: "Locker" },
      { duration: 480, value: 280, end_value: 280, zone: 4, label: "Schwelle" },
      { duration: 300, value: 120, end_value: 120, zone: 1, label: "Locker" },
      { duration: 480, value: 280, end_value: 280, zone: 4, label: "Schwelle" },
      { duration: 900, value: 120, end_value: 120, zone: 1, label: "Locker" },
    ] };
    const unit = (id, name, pending) => ({ id, local_id: id, payload_hash: "a".repeat(64), date, name, type: "Ride", duration_minutes: 60, workout_profile: profile, session_focus: "threshold", focus_origin: "set", push_pending: pending });
    state.data.configured = { ...(state.data.configured || {}), intervals: true };
    state.data.calendar_display = { past_weeks: 0, future_weeks: 1 };
    state.data.training_calendar = [
      unit("sent-unit", "Bereits gesendet", { intervals: false }),
      unit("new-unit", "Nie gesendet", { intervals: true }),
      unit("changed-unit", "Seit dem Senden geändert", { intervals: true }),
    ];
    renderPlanned(state.data.training_calendar);
    document.querySelectorAll(".planned-week").forEach((week) => { week.open = true; });
    return date;
  });
}

test("@responsive the calendar week offers the sync button only for units still to send", async ({ page, request }) => {
  await openCalendar(page, request);
  const date = await renderUnits(page);
  const day = page.locator(`.planned-day[data-date="${date}"]`);
  const card = (name) => day.locator(".planned-entry").filter({ hasText: name });
  // A unit that is already sent shows nothing: no button, no icon, no status text.
  await card("Bereits gesendet").scrollIntoViewIfNeeded();
  await expect(card("Bereits gesendet").locator(".planned-sync-button")).toHaveCount(0);
  await expect(card("Bereits gesendet").locator("summary")).not.toContainText(/synchron/i);
  // Never sent and changed units each get one compact button on the sport line.
  for (const name of ["Nie gesendet", "Seit dem Senden geändert"]) {
    const entry = card(name);
    const button = entry.locator(".planned-sync-button");
    await expect(button).toHaveCount(1);
    await expect(button).toHaveText("Synchronisieren");
    await expect(entry.locator(".planned-session-line .planned-sync-button")).toHaveCount(1);
    const [buttonBox, entryBox] = await Promise.all([button.boundingBox(), entry.boundingBox()]);
    expect(buttonBox.height).toBeGreaterThanOrEqual(28);
    expect(buttonBox.height).toBeLessThan(44);
    expect(buttonBox.width).toBeLessThan(entryBox.width * 0.6);
    // The touch target stays 44 px tall through the hit area.
    const hit = await button.evaluate((element) => {
      const style = getComputedStyle(element, "::before");
      return Number.parseFloat(style.height) || 0;
    });
    expect(hit).toBeGreaterThanOrEqual(44);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
});

test("@responsive an endurance unit shows a tall zone-coloured workout profile", async ({ page, request }, testInfo) => {
  await openCalendar(page, request);
  const date = await renderUnits(page);
  const profile = page.locator(`.planned-day[data-date="${date}"] .planned-entry`).first().locator(".calendar-workout-profile");
  await profile.scrollIntoViewIfNeeded();
  const box = await profile.boundingBox();
  expect(box.height).toBeGreaterThanOrEqual(44);
  expect(box.height).toBeLessThanOrEqual(52);
  // Bars differ in height by intensity, zones differ in colour, intervals stay separate shapes.
  const shapes = await profile.locator("polygon").evaluateAll((nodes) => nodes.map((node) => ({
    zone: node.getAttribute("data-zone"),
    fill: getComputedStyle(node).fill,
    top: Math.min(...node.getAttribute("points").split(" ").map((point) => Number(point.split(",")[1]))),
    left: Number(node.getAttribute("points").split(" ")[0].split(",")[0]),
    right: Number(node.getAttribute("points").split(" ")[3].split(",")[0]),
  })));
  expect(shapes).toHaveLength(5);
  expect(new Set(shapes.map((shape) => shape.fill)).size).toBe(2);
  expect(shapes.find((shape) => shape.zone === "4").top).toBeLessThan(shapes.find((shape) => shape.zone === "1").top);
  for (let index = 1; index < shapes.length; index += 1) expect(shapes[index].left).toBeGreaterThan(shapes[index - 1].right);
  await page.locator(`.planned-day[data-date="${date}"]`).screenshot({ path: testInfo.outputPath("calendar-week-unit.png") });
});

test("@responsive the profile has no weekly plan editor", async ({ page, request }) => {
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  await page.goto("/#more/profile");
  await page.waitForFunction(() => state.initialStateLoaded);
  await expect(page.locator("#profileForm")).toBeAttached();
  await expect(page.locator("#weeklyPlanEditor")).toHaveCount(0);
  await expect(page.locator("#profileForm [name='weekly_plan']")).toHaveCount(0);
  await expect(page.locator("#profileForm legend", { hasText: "Wochenplan" })).toHaveCount(0);
  const profile = await page.evaluate(async () => api("/api/profile"));
  expect(profile).not.toHaveProperty("weekly_fallback");
  expect(profile.profile).not.toHaveProperty("weekly_plan");
});
