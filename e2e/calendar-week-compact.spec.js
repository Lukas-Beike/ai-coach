const { test, expect } = require("@playwright/test");

async function openCalendar(page, request) {
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  await page.goto("/#plan/overview");
  await page.waitForFunction(() => state.initialStateLoaded);
  await page.evaluate(async () => { await AppRouter.navigate("plan/overview", { historyMode: "replace" }); });
  await expect(page.locator(".planned-day.is-today")).toHaveCount(1);
}

test("@responsive compact calendar week collapses past days, groups repeats and keeps one conflict style", async ({ page, request }, testInfo) => {
  await openCalendar(page, request);
  const week = page.locator(".planned-week").filter({ has: page.locator(".planned-day.is-today") });
  // Past days with sessions are one closed line with a count; today stays open.
  const pastDays = week.locator(".planned-day.is-past");
  if (await pastDays.count()) {
    await expect(pastDays.first().locator(".planned-day-toggle")).not.toHaveAttribute("open", "");
    await expect(pastDays.first().locator(".planned-day-overview")).toContainText("Einheit");
    await expect(week.locator(".planned-day.is-today .planned-day-toggle")).toHaveCount(0);
  }
  // The week summary is a fixed grid without dash-only load rows.
  const metrics = week.locator(".planned-week-metrics");
  await expect(metrics).not.toContainText("Belastung absolviert");
  await expect(metrics).not.toContainText(/ohne \d+ Aktivit/);
  // Every session is one compact row; a planned session is styled apart from completed ones.
  const planned = page.locator(".planned-entry.is-planned, .planned-entry.is-today").first();
  await planned.scrollIntoViewIfNeeded();
  const styles = await planned.evaluate((element) => {
    const completed = document.querySelector(".planned-entry.is-completed");
    return { planned: getComputedStyle(element).borderTopStyle, completed: completed ? getComputedStyle(completed).borderTopStyle : "solid" };
  });
  expect(styles.planned).toBe("dashed");
  expect(styles.completed).toBe("solid");
  for (const row of await page.locator(".planned-entry:not([open]) > summary").all()) {
    if (!(await row.isVisible())) continue;
    // A plain row stays compact; a conflict adds one component with its 44 px action.
    const limit = (await row.locator(".planned-conflict").count()) ? 200 : 130;
    expect((await row.boundingBox()).height).toBeLessThan(limit);
  }
  // Conflicts: one component with one action, no marker or conflict pills, calendar text not link-coloured.
  await expect(page.locator(".planned-badge.is-conflict, .planned-badge.is-marker")).toHaveCount(0);
  const conflict = page.locator(".planned-conflict").first();
  if (await conflict.count()) {
    await expect(conflict.getByRole("button")).toHaveCount(1);
    await expect(conflict.getByRole("button")).toHaveText("Mit Coach lösen");
    const message = await conflict.evaluate((element) => {
      let sent = null;
      const original = globalThis.askCoach;
      globalThis.askCoach = (text) => { sent = text; };
      element.querySelector("button").click();
      globalThis.askCoach = original;
      return { sent, open: element.closest("details").open };
    });
    expect(message.sent).toMatch(/kollidiert mit: .+\. Schlage eine Anpassung vor\.$/);
    expect(message.open).toBe(false);
  }
  const calendarNote = page.locator(".planned-day-calendar").first();
  if (await calendarNote.count()) {
    const colours = await calendarNote.evaluate((element) => [getComputedStyle(element).color, getComputedStyle(document.querySelector(".planned-week-summary")).color]);
    expect(colours[0]).toBe(colours[1]);
  }
  // A zone legend accompanies weeks that show workout profiles.
  const profileWeeks = page.locator(".planned-week").filter({ has: page.locator(".calendar-workout-profile") });
  for (const profileWeek of await profileWeeks.all()) await expect(profileWeek.locator(".planned-zone-legend")).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await week.screenshot({ path: testInfo.outputPath("calendar-week-compact.png") });
});

test("@responsive opening a single calendar entry and a grouped row shows their details", async ({ page, request }) => {
  await openCalendar(page, request);
  const entry = page.locator(".planned-day.is-today .planned-entry, .planned-day.is-today .planned-group").first();
  await entry.scrollIntoViewIfNeeded();
  await entry.locator(":scope > summary").click();
  await expect(entry).toHaveAttribute("open", "");
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
