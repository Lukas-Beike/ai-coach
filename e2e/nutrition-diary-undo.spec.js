const { test, expect } = require("@playwright/test");

const DAY = "2026-11-05";
const BOWL = {
  id: "entry-bowl", meal_date: DAY, meal_type: "lunch", logged_at: `${DAY}T12:00:00`, logged_time_known: false,
  description: "Bowl", kcal: 668, carbs_g: 102, protein_g: 27.2, fat_g: 14.8, source: "manual", sync_state: "local", nutrition_basis: { kind: "manual" },
};
const PRODUCT = {
  id: "product-1", name: "Skyr", brand: "Fixture", basis_amount: 100, basis_unit: "g", kcal: 63, carbs_g: 4, protein_g: 11, fat_g: 0.2,
  source: "packaging_label", status: "active", favorite: true,
};

test("@responsive diary shows decimal commas and offers undo and delete for back-filled meals", async ({ page }) => {
  let entries = [BOWL];
  let created = null;
  const undone = [];
  const change = (action, id) => ({ id: `change-${action}-${id}`, entity_type: "nutrition_entry", action, after_hash: `hash-${id}` });
  await page.route("**/api/nutrition/day**", (route) => route.fulfill({ json: {
    ok: true, date: DAY, entry_count: entries.length, entries,
    total_kcal: entries.length ? 668 : 0, total_carbs_g: 102, total_protein_g: 27.2, total_fat_g: 14.8,
  } }));
  await page.route("**/api/nutrition/products**", (route) => route.fulfill({
    json: route.request().url().includes("source=database") ? { ok: true, foods: [] } : { ok: true, products: [PRODUCT] },
  }));
  await page.route("**/api/nutrition/entry/delete", (route) => {
    entries = [];
    return route.fulfill({ json: { ok: true, status: "ok", deleted_id: BOWL.id, change: change("delete", BOWL.id) } });
  });
  await page.route("**/api/nutrition/entry", (route) => {
    created = route.request().postDataJSON();
    return route.fulfill({ json: { ok: true, entry: { ...BOWL, id: "entry-new" }, change: change("create", "new") } });
  });
  await page.route("**/api/change-history/undo", (route) => {
    const body = route.request().postDataJSON();
    undone.push(body);
    if (body.change_id === "change-delete-entry-bowl") entries = [BOWL];
    return route.fulfill({ json: { ok: true } });
  });

  await page.goto("/#nutrition/diary");
  const card = page.locator("#nutritionEntries .nutrition-card");
  await expect(card).toContainText("668 kcal · KH 102 g · Protein 27,2 g · Fett 14,8 g");
  await expect(card.locator("h3")).toHaveText("Mittagessen");

  await card.getByRole("button", { name: /löschen/i }).click();
  await expect(page.locator("#confirmationDialog")).toBeVisible();
  await page.locator("#confirmationDialogAccept").click();
  await expect(card).toHaveCount(0);
  await expect(page.locator("#nutritionStatus")).toContainText("Mahlzeit gelöscht.");
  await page.locator("#nutritionStatus").getByRole("button", { name: "Rückgängig" }).click();
  await expect(card).toHaveCount(1);
  expect(undone[0]).toMatchObject({ change_id: "change-delete-entry-bowl", expected_current_hash: "hash-entry-bowl" });

  await page.goto("/#nutrition/products");
  await page.locator("#nutritionProducts .nutrition-product-card").getByRole("button", { name: "Verwenden" }).click();
  await page.locator("#nutritionProductUseAmount").fill("50");
  await page.locator("#nutritionProductUseAdd").click();
  await expect(page.locator("#nutritionProductStatus")).toContainText("als Snack erfasst");
  expect(created).toMatchObject({ product_id: PRODUCT.id, meal_date: DAY, meal_type: "snack" });
  expect(created.logged_at).toBeUndefined();
  await page.locator("#nutritionProductStatus").getByRole("button", { name: "Rückgängig" }).click();
  await expect(page.locator("#nutritionProductStatus")).toHaveText("Zurückgenommen.");
  expect(undone[1]).toMatchObject({ change_id: "change-create-new" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
