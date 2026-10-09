const { test, expect } = require("@playwright/test");

// Desktop-only spec. CI uses a fresh disposable container per spec, so the
// local deletion is safe there. Deleting local data also removes the login
// sessions, so a retry would start logged out and is disabled.
test.describe.configure({ retries: 0 });
const REQUIRED_TEXT = "LOKALE DATEN LÖSCHEN";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#loginDialog")).toBeHidden();
  await page.waitForFunction(() => state.initialStateLoaded);
});

test("local data deletion requires the exact confirmation text", async ({ page }) => {
  await page.goto("/#more/privacy");
  const panel = page.locator('details[data-more-segment-panel="privacy"]');
  await expect(panel).toBeVisible();
  if (!(await panel.evaluate((element) => element.open))) {
    await panel.locator("summary").click();
  }

  await page.locator("#privacyDeleteButton").click();
  const dialog = page.locator("#confirmationDialog");
  await expect(dialog).toBeVisible();

  const hint = dialog.locator("#confirmationDialogExpected");
  await expect(hint).toBeVisible();
  await expect(hint).toHaveText(`Tippe „${REQUIRED_TEXT}“ zur Bestätigung.`);

  const input = page.locator("#confirmationDialogInput");
  await expect(input).toHaveAttribute("aria-describedby", "confirmationDialogExpected");
  const accept = page.locator("#confirmationDialogAccept");
  await expect(accept).toHaveText("Endgültig löschen");
  await expect(accept).toBeDisabled();

  await expect(page.getByRole("button", { name: "Erst Backup erstellen" })).toBeVisible();

  await input.fill("lokale daten löschen");
  await expect(accept).toBeDisabled();

  await input.fill(REQUIRED_TEXT);
  await expect(accept).toBeEnabled();

  await accept.click();
  await expect(page.locator("#privacyDeleteResult")).toContainText("Lokale Datenklassen gelöscht");
  // The deleted sessions end the current login; the app must return to the login dialog.
  await expect(page.locator("#loginDialog")).toBeVisible();
});
