const { test, expect } = require("@playwright/test");

test("a loaded area is stored on the device before a delayed area arrives @responsive", async ({ page }) => {
  await page.route("**/api/state/events*", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => Boolean(localStorage.getItem("coach-state-snapshot")))).toBe(true);
  await page.evaluate(() => localStorage.removeItem("coach-state-snapshot"));

  let release;
  const held = new Promise((resolve) => { release = resolve; });
  let performanceHeld = false;
  await page.route("**/api/performance", async (route) => {
    performanceHeld = true;
    await held;
    await route.continue();
  });
  await page.reload();
  await expect(page.locator("#appShell")).toBeVisible();
  // The library area is stored while the performance response is still outstanding.
  await expect.poll(() => page.evaluate(() => Array.isArray(JSON.parse(localStorage.getItem("coach-state-snapshot") || "null")?.data?.library))).toBe(true);
  expect(performanceHeld).toBe(true);
  expect(await page.evaluate(() => state.loadedAreas.has("performance"))).toBe(false);
  release();
  await expect.poll(() => page.evaluate(() => state.loadedAreas.has("performance"))).toBe(true);
  await expect.poll(() => page.evaluate(() => Boolean(JSON.parse(localStorage.getItem("coach-state-snapshot") || "null")?.data?.performance))).toBe(true);
});
