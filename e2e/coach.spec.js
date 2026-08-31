const { test, expect } = require("@playwright/test");
const { AxeBuilder } = require("@axe-core/playwright");

const APP_PASSWORD = process.env.E2E_APP_PASSWORD;
if (!APP_PASSWORD || APP_PASSWORD.length < 12) {
  throw new Error("E2E_APP_PASSWORD must be set to a fake password of at least 12 characters.");
}

const navigation = [
  ["Coach", "chatPanel"],
  ["Aktivitäten", "activitiesPanel"],
  ["Geplant", "workoutsPanel"],
  ["Leistungsdaten", "dataPanel"],
  ["Profil", "profilePanel"],
  ["Einstellungen", "settingsPanel"],
];

async function login(page) {
  await page.goto("/");
  const loginDialog = page.locator("#loginDialog");
  await expect(loginDialog).toBeVisible();
  await page.getByLabel("Passwort").fill(APP_PASSWORD);
  await page.getByRole("button", { name: "Anmelden" }).click();
  await page.getByLabel("Passwort").fill("");
  await expect(loginDialog).toBeHidden();
  await expect(page.locator("#appShell")).toBeVisible();
}

function installBrowserGuards(page) {
  const browserErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => browserErrors.push(`page: ${error.message}`));
  return browserErrors;
}

async function expectNoBrowserErrorsOrOverflow(page, browserErrors) {
  expect(browserErrors, "browser console/page errors").toEqual([]);
  const overflow = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    body: document.body.scrollWidth > document.body.clientWidth + 1,
  }));
  expect(overflow, "horizontal overflow").toEqual({ document: false, body: false });
}

test.describe("critical browser states", () => {
  test("login, main views, dialog and profile form state", async ({ page }, testInfo) => {
    const browserErrors = installBrowserGuards(page);

    await page.goto("/");
    await expect(page.locator("#loginDialog")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
    await page.getByLabel("Passwort").fill(APP_PASSWORD);
    await page.getByRole("button", { name: "Anmelden" }).click();
    await page.getByLabel("Passwort").fill("");
    await expect(page.locator("#loginDialog")).toBeHidden();
    await expect(page.locator("#appShell")).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("coach-core.png"), fullPage: true });

    for (const [label, panelId] of navigation) {
      await page.getByRole("button", { name: label, exact: true }).click();
      await expect(page.locator(`#${panelId}`)).toHaveClass(/active/);
      await expect(page.getByRole("button", { name: label, exact: true })).toHaveAttribute("aria-current", "page");
    }

    await page.getByRole("button", { name: "Geplant", exact: true }).click();
    const checkinButton = page.getByRole("button", { name: /Tages-Check-in/ }).first();
    await expect(checkinButton).toBeVisible();
    await checkinButton.click();
    const checkinDialog = page.locator("#checkinDialog");
    await expect(checkinDialog).toBeVisible();
    await expect(checkinDialog.getByRole("heading", { name: "Tages-Check-in" })).toBeVisible();
    await expect(checkinDialog.getByLabel("Tagesform")).toBeVisible();
    await checkinDialog.getByRole("button", { name: "Schließen" }).click();
    await expect(checkinDialog).toBeHidden();

    await page.getByRole("button", { name: "Profil", exact: true }).click();
    const profileName = page.getByLabel("Name");
    await profileName.fill("Fixture Athlete");
    await expect(page.locator("#profileDirtyIndicator")).toBeVisible();
    await expect(page.getByRole("button", { name: "Athletenkontext speichern" })).toBeEnabled();

    await expectNoBrowserErrorsOrOverflow(page, browserErrors);
  });

  test("core views satisfy WCAG AA checks", async ({ page }, testInfo) => {
    const browserErrors = installBrowserGuards(page);
    await page.goto("/");
    const loginResults = await new AxeBuilder({ page })
      .include("#loginDialog")
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();
    expect(loginResults.violations, "Login accessibility violations").toEqual([]);
    await login(page);

    for (const [label, panelId] of navigation.filter(([name]) => ["Coach", "Profil", "Einstellungen"].includes(name))) {
      await page.getByRole("button", { name: label, exact: true }).click();
      await expect(page.locator(`#${panelId}`)).toHaveClass(/active/);
      const results = await new AxeBuilder({ page })
        .include(`#${panelId}`)
        .withTags(["wcag2a", "wcag2aa"])
        .analyze();
      expect(results.violations, `${label} accessibility violations`).toEqual([]);
    }

    await expectNoBrowserErrorsOrOverflow(page, browserErrors);
    await page.screenshot({ path: testInfo.outputPath("settings-core.png"), fullPage: true });
  });
});
