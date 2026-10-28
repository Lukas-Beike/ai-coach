const { test, expect } = require("@playwright/test");
const { expandConnections } = require("./helpers/connections");

test("@responsive Yazio shows a checked login and refreshes its local status", async ({ page }, testInfo) => {
  let status = { status: "unchecked", checked_at: null };
  await page.route("**/api/nutrition/yazio/status", (route) => route.fulfill({ json: status }));
  await page.route("**/api/nutrition/yazio/check", (route) => {
    status = { status: "success", checked_at: "2026-01-01T12:00:00Z" };
    return route.fulfill({ json: status });
  });
  await page.goto("/#more/connections");
  await expect(page.locator("#appShell")).toBeVisible();
  await expandConnections(page);
  await expect(page.locator("#yazioConnectionStatus")).toHaveText("Noch nicht geprüft");
  await page.locator("#yazioCheckButton").click();
  await expect(page.locator("#yazioConnectionStatus")).toHaveText("Anmeldung erfolgreich");
  await expect(page.locator("#yazioConnectionDetail")).toContainText("Geprüft:");
  await page.locator("#yazioConnectionStatus").locator("xpath=ancestor::article").screenshot({ path: testInfo.outputPath("yazio-connection.png") });
  status = { status: "unchecked", checked_at: null };
  await page.evaluate(() => handleSyncStatus({ running: false }));
  await expect(page.locator("#yazioConnectionStatus")).toHaveText("Noch nicht geprüft");
});
