const { test, expect } = require("@playwright/test");
const { expandConnections } = require("./helpers/connections");

// The fixture runtime has no Intervals.icu or Garmin credentials, so provider
// actions must be disabled and the setup banner must be shown.

// The slim line shows as text on a tall screen; under 500 px height it is only a count.
async function tallScreen(page) {
  await page.setViewportSize({ width: page.viewportSize().width, height: 800 });
}

test("@responsive provider sync actions are disabled with a setup hint without configuration", async ({ page }) => {
  await page.goto("/#more/connections");
  await expect(page.locator("#appShell")).toBeVisible();
  await expandConnections(page);
  await expect(page.locator("#intervalsConnectionStatus")).not.toHaveText("Status wird geprüft…");
  await expect(page.locator("#systemIntervalsSyncButton")).toHaveCount(0);
  await expect(page.locator("#systemIntervalsFullResyncButton")).toHaveCount(0);
  await expect(page.locator("#garminSyncButton")).toBeDisabled();
  await expect(page.locator("#garminFullResyncButton")).toBeDisabled();

  const intervalsHint = page.locator("#intervalsSetupHint");
  await expect(intervalsHint).toBeVisible();
  await expect(intervalsHint).toContainText("Intervals.icu ist nicht konfiguriert");
  await expect(intervalsHint).toContainText("INTERVALS_API_KEY");
  await expect(page.locator("#garminSetupHint")).toBeVisible();
  // A-043: the hint names both in-app ways to connect Garmin.
  await expect(page.locator("#garminSetupHint")).toHaveText("Garmin ist nicht verbunden. Melde dich unter „Zugangsdaten“ an oder hinterlege dort einen Schlüssel der Garmin Personal API.");
});

test("@responsive the missing Intervals.icu key is one slim line that can be dismissed for the session", async ({ page }) => {
  await tallScreen(page);
  await page.goto("/#coach");
  const strip = page.locator("#statusStrip");
  await expect(strip).toBeVisible();
  await expect(strip).toContainText("Intervals.icu-API-Schlüssel fehlt");
  await expect(strip).toHaveAttribute("data-level", "info");
  await strip.getByRole("button", { name: "Für diese Sitzung ausblenden" }).click();
  await expect(strip).toBeHidden();
  expect(await page.evaluate(() => sessionStorage.getItem("intervalsCoachSetupBannerDismissed"))).toBe("1");
  expect(await page.evaluate(() => localStorage.getItem("intervalsCoachSetupBannerDismissed"))).toBeNull();

  await page.reload();
  await page.goto("/#more/connections");
  await expandConnections(page);
  await expect(page.locator("#intervalsConnectionStatus")).not.toHaveText("Status wird geprüft…");
  await expect(strip).toBeHidden();
  await expect(page.locator("#intervalsSetupHint")).toBeVisible();
});

test("@responsive the setup line is shown on every tab and Jetzt einrichten opens the connections segment", async ({ page }) => {
  await tallScreen(page);
  await page.goto("/#plan/overview");
  const strip = page.locator("#statusStrip");
  await expect(strip).toBeVisible();
  await page.goto("/#more/profile");
  await expect(strip).toBeVisible();
  await strip.getByRole("link", { name: "Jetzt einrichten" }).click();
  await expect(page).toHaveURL(/#more\/connections$/);
  await expect(page.locator('details[data-more-segment-panel="connections"]')).toHaveAttribute("open", "");
  await expect(page.locator("#intervalsSetupHint")).toBeVisible();
});

test("@responsive the setup line names the missing item compactly without server-configuration advice", async ({ page }) => {
  await tallScreen(page);
  await page.goto("/#coach");
  const strip = page.locator("#statusStrip");
  await expect(strip).toBeVisible();
  await expect(strip).toContainText("Intervals.icu-API-Schlüssel fehlt");
  await expect(strip).not.toContainText(/Serverkonfiguration|Einrichtung nötig|Ergänze/);
  const link = strip.getByRole("link", { name: "Jetzt einrichten" });
  const dismiss = strip.getByRole("button", { name: "Für diese Sitzung ausblenden" });
  const [linkBox, dismissBox, stripBox] = await Promise.all([link.boundingBox(), dismiss.boundingBox(), strip.boundingBox()]);
  // Link and dismiss share one row, and the line stays about one text line plus one touch row.
  expect(Math.abs(linkBox.y - dismissBox.y)).toBeLessThan(4);
  expect(stripBox.height).toBeLessThanOrEqual(96);
});
