const { test, expect } = require("@playwright/test");

test("@responsive nutrition week shows coverage, signed balance and missing days without fueling", async ({ page }) => {
  let fail = false;
  let fuelingRequests = 0;
  page.on("request", (request) => { if (request.url().includes("/nutrition/fueling")) fuelingRequests += 1; });
  await page.route("**/api/nutrition/week", (route) => fail ? route.abort() : route.fulfill({ json: {
    start_date: "2026-09-29", end_date: "2026-10-05", balance_kcal: 500, balance_days: 5,
    averages: { intake_kcal: { value: 2200, days: 6 }, expenditure_kcal: { value: 2100, days: 5 }, carbs_g: { value: 250, days: 4 }, protein_g: { value: 100, days: 6 }, fat_g: { value: null, days: 0 } },
    days: Array.from({ length: 7 }, (_, index) => ({ date: `2026-${index < 2 ? "09" : "10"}-${String(index < 2 ? 29 + index : index - 1).padStart(2, "0")}`, intake_kcal: index < 6 ? 2200 : null, expenditure_kcal: index < 5 ? 2100 : null, balance_kcal: index < 5 ? 100 : null })),
  } }));
  await page.goto("/#nutrition/week");
  const week = page.locator("#nutritionWeek");
  await expect(week).toBeVisible();
  await expect(page.locator("#nutritionDiary")).toBeHidden();
  await expect(week).toContainText("29.09.2026 – 05.10.2026");
  await expect(week).toContainText("Kalorienüberschuss");
  await expect(week).toContainText("+500 kcal");
  await expect(week).toContainText("5 von 7 Tagen · Teilbilanz");
  const intake = week.locator(".nutrition-total").filter({ hasText: "Ø Aufnahme" });
  await expect(intake).toContainText("2.200 kcal");
  await expect(intake).toContainText("6 von 7 Tagen");
  await expect(week.locator(".nutrition-total").filter({ hasText: "Ø Fett" })).toContainText("Nicht verfügbar");
  await expect(week.locator(".nutrition-week-chart-day")).toHaveCount(7);
  await expect(week.locator(".nutrition-week-chart-day").first()).toContainText("2.200 kcal");
  await expect(week.locator(".nutrition-week-chart-track.is-missing")).toHaveCount(3);
  await week.getByText("Tageswerte anzeigen", { exact: true }).click();
  await expect(week.locator("tbody tr")).toHaveCount(7);
  await expect(week.locator("tbody tr").last().locator("td")).toHaveText(["–", "–", "–"]);
  await expect(page.locator("#nutritionFueling, #trainingFueling")).toHaveCount(0);
  expect(fuelingRequests).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.locator('[data-nutrition-segment="diary"]').click();
  await expect(week).toBeHidden();
  await expect(page.locator("#nutritionDiary")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Trainingsverpflegung" })).toHaveCount(0);
  fail = true;
  await page.locator('[data-nutrition-segment="week"]').click();
  // A failed refresh keeps the last loaded week on this device and says so.
  await expect(week).toContainText("Gespeicherter Stand. Aktualisierung fehlgeschlagen");
  await expect(week).toContainText("+500 kcal");
  await expect(week.locator(".nutrition-week-chart-day")).toHaveCount(7);
  await page.evaluate(() => localStorage.removeItem("coach-view-cache"));
  await page.locator('[data-nutrition-segment="diary"]').click();
  await page.locator('[data-nutrition-segment="week"]').click();
  await expect(week).toContainText("Wochenübersicht konnte nicht geladen werden");
  await expect(week.locator("#nutritionWeekTotals")).toBeEmpty();
  await expect(week.locator("#nutritionWeekChart")).toBeEmpty();
  await expect(week.locator("#nutritionWeekDetails")).toBeHidden();
});
