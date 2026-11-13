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
  await expect(page.locator("#yazioConnectionStatus")).toHaveText("Nicht geprüft");
  await expect(page.locator("#yazioConnectionDetail")).toHaveText("Noch nicht geprüft");
  await page.locator("#yazioCheckButton").click();
  await expect(page.locator("#yazioConnectionStatus")).toHaveText("Verbunden");
  await expect(page.locator("#yazioConnectionDetail")).toContainText("Anmeldung erfolgreich");
  await expect(page.locator("#yazioConnectionDetail")).toContainText("Geprüft:");
  await page.locator("#yazioConnectionStatus").locator("xpath=ancestor::details[1]").screenshot({ path: testInfo.outputPath("yazio-connection.png") });
  status = { status: "unchecked", checked_at: null };
  await page.evaluate(() => handleSyncStatus({ running: false }));
  await expect(page.locator("#yazioConnectionStatus")).toHaveText("Nicht geprüft");
});

test("@responsive Yazio shows the server's last check or lookup after a reload without checking", async ({ page }) => {
  let status = { status: "unchecked", checked_at: null };
  const posts = [];
  await page.route("**/api/nutrition/yazio/status", (route) => route.fulfill({ json: status }));
  page.on("request", (request) => { if (request.method() === "POST") posts.push(request.url()); });
  await page.goto("/#more/connections");
  await expandConnections(page, ["yazio"]);
  await expect(page.locator("#yazioConnectionStatus")).toHaveText("Nicht geprüft");
  for (const [next, chip] of [["success", "Verbunden"], ["unavailable", "Fehler"], ["auth_failed", "Fehler"]]) {
    status = { status: next, checked_at: "2026-01-01T12:00:00Z" };
    await page.reload();
    await expandConnections(page, ["yazio"]);
    await expect(page.locator("#yazioConnectionStatus")).toHaveText(chip);
  }
  expect(posts.filter((url) => url.includes("/yazio/check"))).toEqual([]);
});
