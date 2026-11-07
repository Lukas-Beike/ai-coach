const { test, expect } = require("@playwright/test");

async function openEntry(page, name) {
  const entry = page.locator(".planned-entry").filter({ hasText: name }).first();
  await expect(entry).toHaveCount(1);
  await entry.evaluate((element) => {
    for (let node = element; node; node = node.parentElement) if (node.tagName === "DETAILS") node.open = true;
  });
  return entry;
}

test("@responsive session focus chip and select on a planned unit", async ({ page, request }) => {
  test.setTimeout(180_000);
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  await page.goto("/#plan/overview");
  await page.waitForFunction(() => state.initialStateLoaded);
  const name = "Tempolauf nach Distanz";
  let entry = await openEntry(page, name);
  const select = entry.locator("select[name='session_focus']");
  await select.scrollIntoViewIfNeeded();
  await expect(select).toBeVisible();
  await expect(select.locator("option[value='threshold']")).toHaveCount(1);
  await expect(select.locator("option[value='sweet_spot']")).toHaveCount(0);
  await expect(entry.locator("[data-focus-chip='derived'] .planned-badge")).toContainText("≈");
  await expect(entry.locator("select[name='strength_intensity']")).toHaveCount(0);
  // The derived focus is offered next to the empty field; one tap sets it.
  await expect(select).toHaveValue("");
  const suggestion = entry.locator(".planned-focus-form .planned-suggestion-chip");
  await expect(suggestion).toHaveText(/^≈ .+ übernehmen$/);
  expect((await suggestion.boundingBox()).height).toBeGreaterThanOrEqual(32);
  const suggested = page.waitForResponse((response) => response.url().includes("/focus") && response.request().method() === "POST");
  await suggestion.click();
  expect((await suggested).ok()).toBeTruthy();
  await expect(suggestion).toHaveCount(0);
  await expect(select).not.toHaveValue("");
  const saved = page.waitForResponse((response) => response.url().includes("/focus") && response.request().method() === "POST");
  await select.selectOption("threshold");
  expect((await saved).ok()).toBeTruthy();
  await expect(entry.locator("[data-focus-chip='set'] .planned-badge")).toHaveText("Schwelle");
  await page.reload();
  await page.waitForFunction(() => state.initialStateLoaded);
  entry = await openEntry(page, name);
  const chip = entry.locator("[data-focus-chip='set'] .planned-badge");
  await expect(chip).toHaveText("Schwelle");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  const hit = await entry.locator("select[name='session_focus']").boundingBox();
  expect(hit.height).toBeGreaterThanOrEqual(32);
  // Restore the fixture unit.
  const cleared = page.waitForResponse((response) => response.url().includes("/focus") && response.request().method() === "POST");
  await entry.locator("select[name='session_focus']").selectOption("");
  expect((await cleared).ok()).toBeTruthy();
});
