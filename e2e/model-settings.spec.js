const { test, expect } = require("@playwright/test");

test("model and speed selection persist with capability checks @responsive", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => AppRouter.navigate("more/coach", { historyMode: "replace" }));
  await page.locator("#modelSettingsTarget").evaluate(el => el.closest("details").open = true);
  const model = page.locator("#modelSelect");
  const speed = page.locator("#serviceTierSelect");
  await expect(model).toHaveValue("gpt-6-luna");
  await expect(speed).toHaveValue("fast");
  await expect(page.locator("#thinkingLevelSelect")).toHaveValue("medium");
  await expect(speed.locator("option")).toHaveCount(2);
  await model.selectOption("gpt-6.1-sol");
  await expect(model).toBeEnabled();
  await expect(speed.locator("option")).toHaveCount(3);
  await speed.selectOption("ultrafast");
  await expect(speed).toBeEnabled();
  await page.reload();
  await page.locator("#modelSettingsTarget").evaluate(el => el.closest("details").open = true);
  await expect(model).toHaveValue("gpt-6.1-sol");
  await expect(speed).toHaveValue("ultrafast");
  await model.selectOption("gpt-6-luna");
  await expect(speed).toHaveValue("fast");
  await expect(speed.locator("option")).toHaveCount(2);
});
