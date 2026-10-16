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

test("@responsive the logout button follows every Mehr segment", async ({ page }) => {
  await page.route("**/api/state/events*", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => Boolean(state.data))).toBe(true);
  for (const segment of ["appearance", "equipment", "connections", "coach", "privacy", "operations"]) {
    await page.goto(`/#more/${segment}`);
    await expect(page.locator(`#settingsPanel [data-more-segment-panel="${segment}"]`).first()).toBeVisible();
    await expect(page.locator("#logoutButton")).toBeVisible();
    const placement = await page.evaluate(() => {
      const logout = document.querySelector("#logoutButton").getBoundingClientRect();
      const panels = [...document.querySelectorAll("#settingsPanel > [data-more-segment-panel]")]
        .map((panel) => panel.getBoundingClientRect())
        .filter((box) => box.height > 0);
      return { logoutTop: logout.top, lowestPanelBottom: Math.max(...panels.map((box) => box.bottom)) };
    });
    expect(placement.logoutTop, segment).toBeGreaterThanOrEqual(placement.lowestPanelBottom);
  }
});
