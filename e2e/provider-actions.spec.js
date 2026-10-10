const { test, expect } = require("@playwright/test");

// The fixture runtime has no Intervals.icu or Garmin credentials, so provider
// actions must be disabled and the setup banner must be shown.

async function expandConnections(page) {
  const section = page.locator('details[data-more-segment-panel="connections"]');
  await expect(section).toBeVisible();
  if (!(await section.evaluate((element) => element.open))) await section.locator("summary").first().click();
  await expect(section).toHaveAttribute("open", "");
}

test("@responsive provider sync actions are disabled with a setup hint without configuration", async ({ page }) => {
  await page.goto("/#more/connections");
  await expect(page.locator("#appShell")).toBeVisible();
  await expandConnections(page);
  await expect(page.locator("#intervalsConnectionStatus")).not.toHaveText("Status wird geprüft…");
  await expect(page.locator("#systemIntervalsSyncButton")).toBeDisabled();
  await expect(page.locator("#systemIntervalsFullResyncButton")).toBeDisabled();
  await expect(page.locator("#garminSyncButton")).toBeDisabled();
  await expect(page.locator("#garminFullResyncButton")).toBeDisabled();

  const intervalsHint = page.locator("#intervalsSetupHint");
  await expect(intervalsHint).toBeVisible();
  await expect(intervalsHint).toContainText("Intervals.icu ist nicht konfiguriert");
  await expect(intervalsHint).toContainText("INTERVALS_API_KEY");
  await expect(page.locator("#garminSetupHint")).toBeVisible();
});

test("@responsive setup banner can be dismissed for the session and stays hidden after reload", async ({ page }) => {
  await page.goto("/#coach");
  const banner = page.locator("#setupBanner");
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("Intervals.icu-API-Schlüssel");
  await banner.getByRole("button", { name: "Für diese Sitzung ausblenden" }).click();
  await expect(banner).toBeHidden();
  expect(await page.evaluate(() => sessionStorage.getItem("intervalsCoachSetupBannerDismissed"))).toBe("1");
  expect(await page.evaluate(() => localStorage.getItem("intervalsCoachSetupBannerDismissed"))).toBeNull();

  await page.reload();
  await page.goto("/#more/connections");
  await expandConnections(page);
  await expect(page.locator("#intervalsConnectionStatus")).not.toHaveText("Status wird geprüft…");
  await expect(banner).toBeHidden();
  await expect(page.locator("#intervalsSetupHint")).toBeVisible();
});

test("@responsive setup banner is shown on every tab and Jetzt einrichten opens the connections segment", async ({ page }) => {
  await page.goto("/#plan/overview");
  const banner = page.locator("#setupBanner");
  await expect(banner).toBeVisible();
  await page.goto("/#more/profile");
  await expect(banner).toBeVisible();
  await banner.getByRole("link", { name: "Jetzt einrichten" }).click();
  await expect(page).toHaveURL(/#more\/connections$/);
  await expect(page.locator('details[data-more-segment-panel="connections"]')).toHaveAttribute("open", "");
  await expect(page.locator("#intervalsSetupHint")).toBeVisible();
});
