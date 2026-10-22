const { test, expect } = require("@playwright/test");

test("@responsive nutrition overview shows consumed sugar and salt with honest missing values", async ({ page }) => {
  let mode = "complete";
  await page.route("**/api/nutrition/day**", (route) => route.fulfill({ json: {
    date: "2026-10-20", entry_count: mode === "empty" ? 0 : 1, entries: [],
    total_kcal: 200, total_carbs_g: 30, total_protein_g: 10, total_fat_g: 5,
    total_sugar_g: mode === "complete" ? 12.5 : null,
    total_salt_g: mode === "complete" ? 0 : null,
    known_intake_totals: { sugar_g: mode === "partial" ? 6.2 : null, salt_g: null },
  } }));
  await page.goto("/#nutrition/diary");
  const sugar = page.locator("#nutritionTotals .nutrition-total").filter({ hasText: "Zucker" });
  const salt = page.locator("#nutritionTotals .nutrition-total").filter({ hasText: "Salz" });
  await expect(sugar).toHaveText("12.5 gZucker");
  await expect(salt).toHaveText("0 gSalz");
  mode = "partial";
  await page.reload();
  await expect(sugar).toHaveText("6.2 gZucker · unvollständig");
  await expect(salt).toHaveText("– gSalz");
  mode = "empty";
  await page.reload();
  await expect(sugar).toHaveText("– gZucker");
  await expect(salt).toHaveText("– gSalz");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
