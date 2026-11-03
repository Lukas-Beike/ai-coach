const { test, expect } = require("@playwright/test");

test("a loaded area is stored on the device before a delayed area arrives @responsive", async ({ page }) => {
  await page.route("**/api/state/events*", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => Boolean(localStorage.getItem("coach-state-snapshot")))).toBe(true);
  // The closing page saves its snapshot on pagehide, after any removal made before the reload. The
  // reloaded page therefore clears it before its scripts run, so the library area checked below is
  // stored by that page alone.
  await page.evaluate(() => sessionStorage.setItem("e2e-clear-snapshot", "1"));
  await page.addInitScript(() => {
    if (sessionStorage.getItem("e2e-clear-snapshot")) {
      sessionStorage.removeItem("e2e-clear-snapshot");
      localStorage.removeItem("coach-state-snapshot");
    }
  });

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
  // The performance read is held: wait until the route has taken it before checking what was stored.
  await expect.poll(() => performanceHeld).toBe(true);
  // The library area is stored while the performance response is still outstanding.
  await expect.poll(() => page.evaluate(() => Array.isArray(JSON.parse(localStorage.getItem("coach-state-snapshot") || "null")?.data?.library))).toBe(true);
  expect(await page.evaluate(() => state.loadedAreas.has("performance"))).toBe(false);
  release();
  await expect.poll(() => page.evaluate(() => state.loadedAreas.has("performance"))).toBe(true);
  await expect.poll(() => page.evaluate(() => Boolean(JSON.parse(localStorage.getItem("coach-state-snapshot") || "null")?.data?.performance))).toBe(true);
});
