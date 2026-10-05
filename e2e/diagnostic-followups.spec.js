const { test, expect } = require("@playwright/test");

test("retained Body Battery is dated instead of being presented as current", async ({ page }) => {
  await page.goto("/#more/connections");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => !state.loadPromise)).toBe(true);
  await page.evaluate(() => renderGarmin({
    available: true, configured: true, source: "library", last_sync_at: "2026-09-08T11:10:00Z",
    morning_body_battery: { status: "ready", sleep_date: "2026-09-07", before_sleep: { value: 30 }, morning: { value: 78 } },
  }));
  await expect(page.locator("#garminDetail")).toContainText("Body Battery am");
  await expect(page.locator("#garminDetail")).toContainText("78 nach dem Aufwachen");
  await expect(page.locator("#garminDetail")).not.toContainText("78 aktuell");
});
