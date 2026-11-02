const { test, expect } = require("@playwright/test");

test("@responsive macro highlights use complete daily values", async ({ page }) => {
  await page.route("**/api/nutrition/day**", async (route) => {
    await route.fulfill({ json: {
      ok: true, date: "2026-01-01", entry_count: 1, entries: [],
      total_kcal: 2700, total_carbs_g: 300, total_protein_g: 220, total_fat_g: 75,
      macro_ranges: { carbs_g: [450, 630], protein_g: [153, 207], fat_g: [60, 90] },
    } });
  });
  await page.goto("/#nutrition/diary");
  const totals = page.locator("#nutritionTotals .nutrition-total");
  await expect(totals.filter({ hasText: "Kohlenhydrate" })).toHaveClass(/nutrition-below-range/);
  await expect(totals.filter({ hasText: "Protein" })).toHaveClass(/nutrition-above-range/);
  await expect(totals.filter({ hasText: "Fett" })).not.toHaveClass(/nutrition-(below|above)-range/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("nutrition day includes reference ranges from the isolated runtime", async ({ page }) => {
  await page.goto("/#nutrition/diary");
  const response = await page.request.get("/api/nutrition/day");
  expect(response.ok()).toBeTruthy();
  const result = await response.json();
  expect(result.macro_ranges).toBeTruthy();
});
