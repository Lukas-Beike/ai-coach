const { test, expect } = require("@playwright/test");

test.describe("login dialog", () => {
  // Start unauthenticated; the project default storage state holds the authenticated session.
  test.use({ storageState: { cookies: [], origins: [] } });

  test("Escape keeps the login dialog open and logout shows it again @responsive", async ({ page }) => {
    const password = process.env.E2E_APP_PASSWORD;
    expect(password, "E2E_APP_PASSWORD must be set to a fake password").toBeTruthy();

    await page.goto("/");
    const loginDialog = page.locator("#loginDialog");
    const passwordInput = page.getByLabel("Passwort", { exact: true });
    await expect(loginDialog).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(loginDialog).toBeVisible();
    await expect(passwordInput).toBeFocused();
    // A repeated Escape may bypass the cancel event in Chromium; the close fallback must reopen the dialog.
    await page.keyboard.press("Escape");
    await expect(loginDialog).toBeVisible();
    await expect(passwordInput).toBeFocused();

    await passwordInput.fill(password);
    await page.getByRole("button", { name: "Anmelden", exact: true }).click();
    await expect(loginDialog).toBeHidden();
    await expect(page.locator("#appShell")).toBeVisible();

    await page.getByRole("link", { name: "Mehr", exact: true }).click();
    await expect(page.locator("#settingsPanel")).toHaveClass(/active/);
    // Logout lives in the Betrieb & Diagnose segment, not in the default settings view.
    await page.locator('a[data-more-segment="operations"]:visible').first().click();
    await page.getByRole("button", { name: "Abmelden", exact: true }).click();
    await page.locator("#confirmationDialogAccept").click();

    await expect(loginDialog).toBeVisible();
    await expect(passwordInput).toBeFocused();
  });

  for (const [status, headers, expected] of [
    [429, { "Retry-After": "600" }, "Zu viele Anmeldeversuche. Bitte in etwa 10 Minuten erneut versuchen."],
    [503, { "Retry-After": "5" }, "Der Server startet gerade oder ist ausgelastet. Bitte in wenigen Sekunden erneut versuchen."],
  ]) {
    test(`a ${status} answer shows its own message instead of the timeout text @responsive`, async ({ page }) => {
      let attempts = 0;
      await page.route("**/api/login", async (route) => {
        attempts += 1;
        await route.fulfill({ status, headers, contentType: "application/json", body: JSON.stringify({ error: "Serverfehler", reason: "mocked" }) });
      });
      await page.goto("/");
      await expect(page.locator("#loginDialog")).toBeVisible();
      await page.getByLabel("Passwort", { exact: true }).fill("any-fake-password");
      await page.getByRole("button", { name: "Anmelden", exact: true }).click();
      await expect(page.locator("#loginError")).toHaveText(expected);
      await expect(page.locator("#loginError")).not.toContainText("25 Sekunden");
      expect(attempts).toBe(1);
    });
  }
});
