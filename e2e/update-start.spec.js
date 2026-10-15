const { test, expect } = require("@playwright/test");

// Marks the stored snapshot as written by earlier assets before the app scripts read it.
async function simulateUpdate(page) {
  await page.addInitScript(() => {
    if (!sessionStorage.getItem("e2e-age-snapshot")) return;
    sessionStorage.removeItem("e2e-age-snapshot");
    const snapshot = JSON.parse(localStorage.getItem("coach-state-snapshot"));
    snapshot.asset = "earlier-assets";
    localStorage.setItem("coach-state-snapshot", JSON.stringify(snapshot));
  });
  await page.evaluate(() => sessionStorage.setItem("e2e-age-snapshot", "1"));
}

async function ready(page) {
  await page.route("**/api/state/events*", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => Boolean(localStorage.getItem("coach-state-snapshot")))).toBe(true);
}

test("a start after an update shows the update loading screen until fresh data loads @responsive", async ({ page }) => {
  await ready(page);
  await simulateUpdate(page);
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  await page.route("**/api/bootstrap?local=1", async (route) => { await held; await route.continue(); });
  await page.reload();
  await expect(page.locator("#authLoading")).toHaveText("Update wird verarbeitet…");
  await expect(page.locator("#appShell")).toBeHidden();
  release();
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator("#authLoading")).toBeHidden();
  await expect.poll(() => page.evaluate(() => readStateSnapshot()?.updated)).toBe(false);
});

test("a start after an update without a reachable server shows the stored data @responsive", async ({ page }) => {
  await ready(page);
  await simulateUpdate(page);
  await page.route("**/api/auth/status", (route) => route.abort());
  await page.reload();
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator("#loginDialog")).not.toBeVisible();
  await expect(page.locator("#authLoading")).toBeHidden();
});

test("a start after an update whose fresh data fails shows the stored data @responsive", async ({ page }) => {
  await ready(page);
  await simulateUpdate(page);
  await page.route("**/api/bootstrap?local=1", (route) => route.abort());
  await page.reload();
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator("#authLoading")).toBeHidden();
  await expect.poll(() => page.evaluate(() => Boolean(state.data && state.replaceDataOnLoad))).toBe(true);
});
