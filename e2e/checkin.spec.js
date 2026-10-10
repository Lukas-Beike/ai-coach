const { test, expect } = require("@playwright/test");

const todayCardFor = (page) => page.locator("#plannedCalendar .planned-day.is-today");
const todayCheckinAction = (page) => todayCardFor(page).locator(".planned-day-checkin button");
const CHECKIN_FIELDS = ["soreness", "stress", "motivation", "session_rpe", "day_form", "available_minutes", "illness", "pain", "availability_notes", "notes"];

const waitForFeedbackLoaded = (page) => expect.poll(() => page.evaluate(() => state.loadedAreas.has("feedback"))).toBe(true);

const fetchCheckin = (page, dateKey) => page.evaluate(async (key) => {
  const data = await api("/api/feedback");
  return (data.checkins || []).find((row) => row.checkin_date === key) || null;
}, dateKey);

const restoreCheckin = (page, original) => {
  const body = {
    checkin_date: original.checkin_date,
    day_status: original.day_status ?? "unknown",
    tag_answers: original.tag_answers ?? {},
    ...Object.fromEntries(CHECKIN_FIELDS.map((field) => [field, original[field] ?? null])),
  };
  return page.evaluate(async (payload) => {
    const result = await api("/api/feedback", { method: "POST", body: JSON.stringify(payload) });
    return result.checkin?.checkin_date ?? null;
  }, body);
};

// The fixture runtime is shared across specs, so today's seeded check-in is captured before each test and restored after it.
let originalTodayCheckin = null;

test.beforeEach(async ({ page }) => {
  await openPlanOverview(page);
  await waitForFeedbackLoaded(page);
  const dateKey = await todayCardFor(page).getAttribute("data-date");
  originalTodayCheckin = await fetchCheckin(page, dateKey);
  if (!originalTodayCheckin) throw new Error("The fixture must seed today's check-in so it can be restored.");
});

test.afterEach(async ({ page }) => {
  if (!originalTodayCheckin) return;
  const restoredDate = await restoreCheckin(page, originalTodayCheckin);
  expect(restoredDate).toBe(originalTodayCheckin.checkin_date);
  originalTodayCheckin = null;
});

const openPlanOverview = async (page) => {
  await page.goto("/#plan/overview");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(todayCardFor(page)).toBeVisible();
};

const saveCheckin = async (page, dayForm, soreness) => {
  const dialog = page.locator("#checkinDialog");
  await todayCheckinAction(page).click();
  await expect(dialog).toBeVisible();
  await dialog.locator('[name="day_form"]').fill(dayForm);
  await dialog.locator('[name="soreness"]').fill(soreness);
  await dialog.getByRole("button", { name: "Tages-Check-in speichern" }).click();
  await expect(dialog).toBeHidden();
};

test("@responsive daily check-in opens from today's card, saves, shows status and survives reload", async ({ page }) => {
  const dialog = page.locator("#checkinDialog");
  await openPlanOverview(page);
  await saveCheckin(page, "E2E check-in: frische Beine", "3");
  await expect(todayCardFor(page).locator(".planned-day-checkin-status")).toContainText("Check-in gespeichert");
  await expect(todayCheckinAction(page)).toHaveText("Check-in bearbeiten");
  await todayCheckinAction(page).click();
  await expect(dialog.locator('[name="day_form"]')).toHaveValue("E2E check-in: frische Beine");
  await expect(dialog.locator('[name="soreness"]')).toHaveValue("3");
  await dialog.getByRole("button", { name: "Schließen" }).click();
  await expect(dialog).toBeHidden();
  await page.reload();
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(todayCardFor(page)).toBeVisible();
  await expect(todayCardFor(page).locator(".planned-day-checkin-status")).toContainText("Check-in gespeichert");
  await todayCheckinAction(page).click();
  await expect(dialog.locator('[name="day_form"]')).toHaveValue("E2E check-in: frische Beine");
  await dialog.getByRole("button", { name: "Schließen" }).click();
});

test("@responsive check-in history asks before replacing an unsaved draft", async ({ page }) => {
  const dialog = page.locator("#checkinDialog");
  const confirmation = page.locator("#confirmationDialog");
  await openPlanOverview(page);
  await saveCheckin(page, "E2E check-in: Ausgangswert", "2");
  await todayCheckinAction(page).click();
  await expect(dialog).toBeVisible();
  await dialog.locator('[name="notes"]').fill("E2E unsaved draft");
  await expect(dialog.locator("#checkinDirtyIndicator")).toBeVisible();
  await dialog.locator(".checkin-history-item").first().click();
  await expect(confirmation).toBeVisible();
  await expect(confirmation).toContainText("Ungespeicherte Änderungen verwerfen?");
  await confirmation.locator("#confirmationDialogCancel").click();
  await expect(confirmation).toBeHidden();
  await expect(dialog.locator('[name="notes"]')).toHaveValue("E2E unsaved draft");
  await expect(dialog.locator("#checkinDirtyIndicator")).toBeVisible();
  await dialog.locator(".checkin-history-item").first().click();
  await expect(confirmation).toBeVisible();
  await confirmation.locator("#confirmationDialogAccept").click();
  await expect(confirmation).toBeHidden();
  await expect(dialog.locator('[name="notes"]')).not.toHaveValue("E2E unsaved draft");
  await expect(dialog.locator("#checkinDirtyIndicator")).toBeHidden();
  await dialog.locator('[name="notes"]').fill("E2E draft kept after closing");
  await dialog.getByRole("button", { name: "Schließen" }).click();
  await expect(dialog).toBeHidden();
  await todayCheckinAction(page).click();
  await expect(confirmation).toBeVisible();
  await confirmation.locator("#confirmationDialogCancel").click();
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('[name="notes"]')).toHaveValue("E2E draft kept after closing");
  await dialog.getByRole("button", { name: "Schließen" }).click();
});

test("Mehr profile opens the daily check-in for today", async ({ page }) => {
  await page.goto("/#more/profile");
  await expect(page.locator("#appShell")).toBeVisible();
  await waitForFeedbackLoaded(page);
  await page.locator("#profileCheckinButton").click();
  const dialog = page.locator("#checkinDialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('[name="checkin_date"]')).toHaveValue(/^\d{4}-\d{2}-\d{2}$/);
  await dialog.getByRole("button", { name: "Schließen" }).click();
  await expect(dialog).toBeHidden();
});
