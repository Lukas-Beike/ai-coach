const { test, expect } = require("@playwright/test");

test("older measurements retain their date and age after a successful fetch", async ({ page }) => {
  await page.goto("/#analysis/performance");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => state.loadedAreas.has("performance") && !state.loadPromise)).toBe(true);
  await page.evaluate(() => {
    displayMetric(document.querySelector("#performanceSummary"), "Synthetic older weight", {
      value: 72, unit: "kg", source: "Garmin Connect", freshness: "current",
      observed_at: "2026-08-12", fetched_at: "2026-09-08T11:10:00Z",
      measurement_status: "earlier", measurement_age_days: 27,
    });
    displayMetric(document.querySelector("#performanceSummary"), "Synthetic undated FTP", {
      value: 300, unit: "W", source: "Garmin Connect", freshness: "current",
      fetched_at: "2026-09-08T11:10:00Z", measurement_status: "unknown",
    });
  });
  const older = page.locator("#performanceSummary > div").filter({ hasText: "Synthetic older weight" });
  await expect(older).toContainText("72 kg");
  await expect(older).toContainText("Messung");
  await expect(older).toContainText("27 Tage alt");
  await expect(older.locator("small").first()).toHaveAttribute("title", /Abgerufen/);
  await expect(page.locator("#performanceSummary")).toContainText("Messdatum unbekannt");
});

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
