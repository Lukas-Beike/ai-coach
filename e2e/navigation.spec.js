const { test, expect } = require("@playwright/test");

test("@responsive each hash navigation renders its target once", async ({ page }) => {
  await page.route("**/api/state/events*", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => Boolean(state.data))).toBe(true);
  await page.evaluate(() => {
    globalThis.__routeRenderCounts = {};
    document.addEventListener("app:route-rendered", (event) => {
      const route = event.detail?.route;
      if (route) globalThis.__routeRenderCounts[route] = (globalThis.__routeRenderCounts[route] || 0) + 1;
    });
  });
  for (const route of ["plan", "nutrition", "analysis", "more", "coach"]) {
    await page.evaluate(async (nextRoute) => {
      const changed = new Promise((resolve) => globalThis.addEventListener("hashchange", resolve, { once: true }));
      const rendered = new Promise((resolve) => document.addEventListener("app:route-rendered", resolve, { once: true }));
      globalThis.location.hash = nextRoute;
      await changed;
      await rendered;
    }, route);
    expect(await page.evaluate((name) => globalThis.__routeRenderCounts[name] || 0, route)).toBe(1);
  }
});

test("@responsive the logout button only appears in Betrieb & Diagnose", async ({ page }) => {
  await page.route("**/api/state/events*", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => Boolean(state.data))).toBe(true);
  for (const segment of ["appearance", "equipment", "connections", "coach"]) {
    await page.goto(`/#more/${segment}`);
    await expect(page.locator(`#settingsPanel [data-more-segment-panel="${segment}"]`).first()).toBeVisible();
    await expect(page.locator("#logoutButton"), segment).toBeHidden();
  }
  await page.goto("/#more/operations");
  await expect(page.locator("#logoutButton")).toBeVisible();
  await expect(page.locator("#privacyExportButton")).toBeHidden();
  await page.evaluate(() => document.querySelectorAll('details[data-more-segment-panel="operations"]').forEach((section) => { section.open = true; }));
  await expect(page.locator("#privacyExportButton")).toBeVisible();
});
