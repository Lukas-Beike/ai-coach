const { test, expect } = require("@playwright/test");
const { expandConnections } = require("./helpers/connections");

test("@responsive the automatic detail loading day is saved and survives a reload", async ({ page }) => {
  await page.goto("/#more/connections");
  await expect(page.locator("#appShell")).toBeVisible();
  await expandConnections(page);
  const input = page.locator("#activityDetailFloorDate");
  await expect(input).toBeVisible();

  await input.fill("2026-10-22");
  await page.locator("#activityDetailFloorSaveButton").click();
  await expect(page.locator("#toast")).toContainText("Startdatum für Detaildaten gespeichert");

  await page.reload();
  await page.goto("/#more/connections");
  await expandConnections(page);
  await expect(page.locator("#activityDetailFloorDate")).toHaveValue("2026-10-22");
});

test("@responsive an empty day is rejected and keeps the saved value", async ({ page }) => {
  await page.goto("/#more/connections");
  await expandConnections(page);
  const input = page.locator("#activityDetailFloorDate");
  await input.fill("2026-10-22");
  await page.locator("#activityDetailFloorSaveButton").click();
  await expect(page.locator("#toast")).toContainText("gespeichert");

  await input.fill("");
  await page.locator("#activityDetailFloorSaveButton").click();
  await expect(page.locator("#toast")).toContainText("Datum");
  const stored = await page.evaluate(async () => (await fetch("/api/settings/activity-detail-floor")).json());
  expect(stored.date).toBe("2026-10-22");
});
