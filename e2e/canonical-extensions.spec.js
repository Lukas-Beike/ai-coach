const { test, expect } = require("@playwright/test");

async function openFixtureActivity(page, request) {
  const seed = await request.get("/api/fixture/activity");
  expect(seed.ok()).toBeTruthy();
  await page.goto("/#plan/overview");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.evaluate(async () => { await AppRouter.navigate("plan/overview", { historyMode: "replace" }); });
  const entry = page.locator(".planned-entry").filter({ hasText: "Synthetic ride <img src=x>" }).first();
  await entry.locator("summary").click();
  await entry.getByRole("button", { name: "Aktivität analysieren" }).click();
  const dialog = page.getByRole("dialog", { name: "Synthetic ride <img src=x>" });
  await expect(dialog.getByRole("button", { name: "Feedback speichern" })).toBeVisible();
  return dialog;
}

test("@responsive activity feedback save shows a receipt whose undo restores it", async ({ page, request }) => {
  const dialog = await openFixtureActivity(page, request);
  await dialog.getByLabel("Notizen").fill("Undo me");
  await dialog.getByRole("button", { name: "Feedback speichern" }).click();
  const status = dialog.locator('.activity-feedback [role="status"]');
  await expect(status).toContainText("Feedback gespeichert");
  await status.getByRole("button", { name: "Rückgängig" }).click();
  await expect(status).toHaveText("Zurückgenommen.");
  await expect(dialog.getByLabel("Notizen")).toHaveValue("");
  const payload = await (await request.get("/api/activities/FixtureCase-1")).json();
  expect(payload.activity_feedback ?? null).toBeNull();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});

test("@responsive local zones save with provider alternatives and undo", async ({ page, request }) => {
  await page.goto("/#more/profile");
  await expect(page.locator("#profilePanel")).toHaveClass(/active/);
  const section = page.locator("#zoneSettings");
  const initialZones = page.waitForResponse((response) => response.url().endsWith("/api/zones") && response.request().method() === "GET");
  await section.locator("summary").click();
  expect((await initialZones).ok()).toBeTruthy();
  await page.evaluate(() => loadZones());
  await page.locator("#zoneSport").selectOption("ride");
  await page.locator("#zoneMetric").selectOption("power");
  await page.getByLabel("FTP (W)").fill("280");
  await page.getByLabel("Zonenobergrenzen (% der FTP)").fill("50, 70, 85, 100, 115, 140, 999");
  await section.getByRole("button", { name: "Lokal speichern" }).click();
  const receipt = page.locator("#zoneReceipt");
  await expect(receipt).toContainText("Lokale Zonen gespeichert");
  await expect(page.locator("#zoneSources")).toContainText("Lokal (gilt)");
  await expect(section.getByRole("button", { name: "Lokale Zonen entfernen" })).toBeVisible();
  let zones = await (await request.get("/api/zones")).json();
  expect(zones.configurations.filter((item) => item.source === "local").map((item) => item.threshold)).toEqual([280]);

  await receipt.getByRole("button", { name: "Rückgängig" }).click();
  await expect(receipt).toHaveText("Zurückgenommen.");
  zones = await (await request.get("/api/zones")).json();
  expect(zones.configurations.filter((item) => item.source === "local")).toEqual([]);
  await expect(section.getByRole("button", { name: "Lokale Zonen entfernen" })).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});

test("@responsive invalid local zones change nothing", async ({ page, request }) => {
  await page.goto("/#more/profile");
  const section = page.locator("#zoneSettings");
  const initialZones = page.waitForResponse((response) => response.url().endsWith("/api/zones") && response.request().method() === "GET");
  await section.locator("summary").click();
  expect((await initialZones).ok()).toBeTruthy();
  await page.evaluate(() => loadZones());
  await page.locator("#zoneMetric").selectOption("heart_rate");
  await page.getByLabel("LTHR (bpm)").fill("170");
  await page.getByLabel("Zonenobergrenzen (bpm)").fill("150, 140, 160");
  await section.getByRole("button", { name: "Lokal speichern" }).click();
  await expect(page.locator(".toast").filter({ hasText: "Die Zonen sind ungültig" })).toBeVisible();
  const zones = await (await request.get("/api/zones")).json();
  expect(zones.configurations.filter((item) => item.source === "local")).toEqual([]);
});
