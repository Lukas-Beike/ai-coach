const { test, expect } = require("@playwright/test");

test("@responsive nutrition week shows coverage, signed balance and missing days without fueling", async ({ page }) => {
  let fail = false;
  let fuelingRequests = 0;
  page.on("request", (request) => { if (request.url().includes("/nutrition/fueling")) fuelingRequests += 1; });
  await page.route("**/api/nutrition/week?days=*", (route) => fail ? route.abort() : route.fulfill({ json: {
    start_date: "2026-09-22", end_date: "2026-10-05", balance_kcal: 500, balance_days: 5,
    averages: { intake_kcal: { value: 2200, days: 6 }, expenditure_kcal: { value: 2100, days: 5 }, carbs_g: { value: 250, days: 4 }, protein_g: { value: 100, days: 6 }, fat_g: { value: null, days: 0 }, sugar_g: { value: 25, days: 3 }, salt_g: { value: null, days: 0 } },
    days: Array.from({ length: 14 }, (_, index) => ({ date: new Date(Date.UTC(2026, 8, 22 + index)).toISOString().slice(0, 10), intake_kcal: index < 6 ? 2200 : null, expenditure_kcal: index < 5 ? 2100 : null, balance_kcal: index < 5 ? 100 : null })),
  } }));
  await page.goto("/#nutrition/week");
  const week = page.locator("#nutritionWeek");
  await expect(week).toBeVisible();
  await expect(page.locator("#nutritionDiary")).toBeHidden();
  await expect(week).toContainText("22.09.2026 – 05.10.2026");
  await expect(week).toContainText("Erfasste Teilbilanz");
  await expect(week).toContainText("+500 kcal");
  await expect(week).toContainText("5 von 14 Tagen · Teilbilanz");
  const intake = week.locator(".nutrition-total").filter({ hasText: "Ø Aufnahme" });
  await expect(intake).toContainText("2.200 kcal");
  await expect(intake).toContainText("6 von 14 Tagen");
  await expect(week.locator(".nutrition-total").filter({ hasText: "Ø Fett" })).toContainText("Nicht verfügbar");
  const sugar = week.locator(".nutrition-total").filter({ hasText: "Ø Zucker" });
  await expect(sugar).toContainText("25 g");
  await expect(sugar).toContainText("3 von 14 Tagen");
  await expect(week.locator(".nutrition-total").filter({ hasText: "Ø Salz" })).toContainText("Nicht verfügbar");
  await expect(week.locator(".nutrition-week-chart-day")).toHaveCount(14);
  await expect(week.locator(".nutrition-week-chart-day").first()).toContainText("2.200 kcal");
  await expect(week.locator(".nutrition-week-chart-track.is-missing")).toHaveCount(17);
  await week.getByText("Tageswerte anzeigen", { exact: true }).click();
  await expect(week.locator("tbody tr")).toHaveCount(14);
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
  await expect(week.locator(".nutrition-week-chart-day")).toHaveCount(14);
  await page.evaluate(() => localStorage.removeItem("coach-view-cache"));
  await page.locator('[data-nutrition-segment="diary"]').click();
  await page.locator('[data-nutrition-segment="week"]').click();
  await expect(week).toContainText("Wochenübersicht konnte nicht geladen werden");
  await expect(week.locator("#nutritionWeekTotals")).toBeEmpty();
  await expect(week.locator("#nutritionWeekChart")).toBeEmpty();
  await expect(week.locator("#nutritionWeekDetails")).toBeHidden();
});

test("@responsive nutrition history switches between 14 days and 12 weeks", async ({ page }) => {
  await page.goto("/#nutrition/week");
  const root = page.locator("#nutritionWeek");
  await expect(root.locator(".nutrition-week-chart-day")).toHaveCount(14);
  await expect(root.getByRole("button", { name: "Letzte 14 Tage", exact: true })).toHaveAttribute("aria-pressed", "true");
  await root.getByRole("button", { name: "12 Wochen", exact: true }).click();
  await expect(root.locator("#nutritionWeekHeading")).toHaveText("Letzte 12 Wochen");
  await expect(root.locator(".nutrition-week-chart-day")).toHaveCount(12);
  await expect(root.locator("#nutritionWeekChartHeading")).toHaveText("Wochendurchschnitte");
  await expect(root.locator("#nutritionWeekStatus")).toContainText("84 Tagen");
  await root.getByText("Tageswerte anzeigen", { exact: true }).click();
  await expect(root.locator("tbody tr")).toHaveCount(84);
  await page.reload();
  await expect(root.locator(".nutrition-week-chart-day")).toHaveCount(14);
  await root.getByRole("button", { name: "12 Wochen", exact: true }).click();
  await expect(root.locator(".nutrition-week-chart-day")).toHaveCount(12);
  await root.getByRole("button", { name: "Letzte 14 Tage", exact: true }).click();
  await expect(root.locator("#nutritionWeekHeading")).toHaveText("Letzte 14 Tage");
  await expect(root.locator(".nutrition-week-chart-day")).toHaveCount(14);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("@responsive nutrition gaps keep expenditure visible without inventing intake", async ({ page }) => {
  await page.route("**/api/nutrition/week?days=*", (route) => {
    const count = Number(new URL(route.request().url()).searchParams.get("days"));
    const days = Array.from({ length: count }, (_, index) => ({ date: new Date(Date.UTC(2026, 0, index + 1)).toISOString().slice(0, 10), intake_kcal: index === 0 ? 2100 : null, expenditure_kcal: 2400, balance_kcal: index === 0 ? -300 : null }));
    return route.fulfill({ json: { start_date: days[0].date, end_date: days.at(-1).date, days, balance_kcal: -300, balance_days: 1,
      averages: { intake_kcal: { value: 2100, days: 1 }, expenditure_kcal: { value: 2400, days: count }, carbs_g: { value: null, days: 0 }, protein_g: { value: null, days: 0 }, fat_g: { value: null, days: 0 }, sugar_g: { value: 25, days: 3 }, salt_g: { value: null, days: 0 } } } });
  });
  await page.goto("/#nutrition/week");
  const root = page.locator("#nutritionWeek");
  await expect(root).toContainText("Erfasste Teilbilanz");
  await expect(root.locator(".nutrition-total").filter({ hasText: "Ø Verbrauch" })).toContainText("14 von 14 Tagen");
  await expect(root.locator(".is-expenditure .is-missing")).toHaveCount(0);
  await expect(root.locator(".is-intake .is-missing")).toHaveCount(13);
  await root.getByRole("button", { name: "12 Wochen", exact: true }).click();
  await expect(root.locator(".nutrition-week-chart-day")).toHaveCount(12);
  const first = root.locator(".nutrition-week-chart-day").first();
  await expect(first.locator(".is-intake")).toContainText("1 von 7 Tagen");
  await expect(first.locator(".is-expenditure")).toContainText("7 von 7 Tagen");
  await expect(root.locator(".is-expenditure .is-missing")).toHaveCount(0);
  await expect(root.locator(".is-intake .is-missing")).toHaveCount(11);
  await expect(root).not.toContainText("Kaloriendefizit");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
