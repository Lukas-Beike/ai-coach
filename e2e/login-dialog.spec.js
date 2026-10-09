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
    await page.getByRole("button", { name: "Abmelden", exact: true }).click();
    await page.locator("#confirmationDialogAccept").click();

    await expect(loginDialog).toBeVisible();
    await expect(passwordInput).toBeFocused();
  });
});
