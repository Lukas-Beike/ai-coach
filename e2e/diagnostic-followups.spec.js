const { test, expect } = require("@playwright/test");

test("older measurements retain their date and age after a successful fetch", async ({ page }) => {
  let performanceRequests = 0;
  await page.route("**/api/performance", (route) => {
    performanceRequests += 1;
    return route.fulfill({ json: {
    performance: {
      available: true,
      metrics: {
        weight_kg: {
          value: 72, unit: "kg", source: "Garmin Connect", freshness: "current",
          observed_at: "2026-08-12", fetched_at: "2026-09-08T11:10:00Z",
          measurement_status: "earlier", measurement_age_days: 27,
        },
        cycling_ftp_watts: {
          value: 300, unit: "W", source: "Garmin Connect", freshness: "current",
          fetched_at: "2026-09-08T11:10:00Z", measurement_status: "unknown",
        },
      },
      current_load: {}, actual_load: {}, recovery: {}, rolling_training: {},
    },
    garmin: {},
    } });
  });
  await page.goto("/#analysis/performance");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => state.loadedAreas.has("performance") && !state.loadPromise)).toBe(true);
  const older = page.locator("#performanceSummary .metric-garmin.metric-editable");
  await expect(older).toContainText("72 kg");
  await expect(older).toContainText("Messung");
  await expect(older).toContainText("27 Tage alt");
  await expect(older.locator("small").first()).toHaveAttribute("title", /Abgerufen/);
  await expect(page.locator("#performanceSummary > section").filter({ hasText: "Radfahren" })).toContainText("Messdatum unbekannt");

  await expect(page.locator("#headerActionButton")).toHaveCount(0);
  await page.reload();
  await expect.poll(() => performanceRequests).toBeGreaterThan(1);
  await page.getByRole("link", { name: "Kalender", exact: true }).click();
  await page.getByRole("link", { name: "Analyse", exact: true }).click();
  await expect(older).toContainText("27 Tage alt");
  await expect(page.locator("#performanceSummary > section").filter({ hasText: "Radfahren" })).toContainText("Messdatum unbekannt");
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
