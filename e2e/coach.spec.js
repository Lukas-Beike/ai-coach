const { test, expect } = require("@playwright/test");
const { AxeBuilder } = require("@axe-core/playwright");

const APP_PASSWORD = process.env.E2E_APP_PASSWORD;
if (!APP_PASSWORD || APP_PASSWORD.length < 12) {
  throw new Error("E2E_APP_PASSWORD must be set to a fake password of at least 12 characters.");
}

const navigation = [
  ["Coach", "chatPanel", "coach"],
  ["Heute", "todayPanel", "today"],
  ["Verlauf", "activitiesPanel", "activities"],
  ["Plan", "workoutsPanel", "planned"],
  ["Leistung", "dataPanel", "performance"],
  ["Mehr", "settingsPanel", "more"],
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

    await page.goto("/#profile");
    await expect(page.locator("#loginDialog")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
    await page.getByLabel("Passwort").fill(APP_PASSWORD);
    await page.getByRole("button", { name: "Anmelden" }).click();
    await page.getByLabel("Passwort").fill("");
    await expect(page.locator("#loginDialog")).toBeHidden();
    await expect(page.locator("#appShell")).toBeVisible();
    await expect(page.locator("#profilePanel")).toHaveClass(/active/);
    await expect(page).toHaveURL(/#profile$/);
    await expect(page.locator("#profilePanel")).toBeFocused();
    await expect(page.locator(".dirty-indicator")).toHaveCount(5);
    const hiddenIndicators = await page.locator(".dirty-indicator").evaluateAll((nodes) => nodes.every((node) => node.hidden));
    expect(hiddenIndicators).toBe(true);
    await expect(page.locator("#remoteDeleteNotice")).toBeHidden();
    for (const [label, panelId, route] of navigation) {
      await page.getByRole("link", { name: label, exact: true }).click();
      await expect(page.locator(`#${panelId}`)).toHaveClass(/active/);
      await expect(page.getByRole("link", { name: label, exact: true })).toHaveAttribute("aria-current", "page");
      await expect(page.getByRole("link", { name: label, exact: true })).toHaveAttribute("href", `#${route}`);
    }

    await page.getByRole("link", { name: "Leistung", exact: true }).click();
    await expect(page).toHaveURL(/#performance$/);
    await page.goBack();
    await expect(page.locator("#settingsPanel")).toHaveClass(/active/);
    await expect(page).toHaveURL(/#more$/);
    await page.goForward();
    await expect(page.locator("#dataPanel")).toHaveClass(/active/);
    await page.goto("/#unknown-route");
    await expect(page.locator("#chatPanel")).toHaveClass(/active/);
    await expect(page).toHaveURL(/#coach$/);

    await page.getByRole("link", { name: "Plan", exact: true }).click();
    await expect(page.locator("#planCalendarSegment")).toBeVisible();
    await expect(page.getByRole("link", { name: "Kalender", exact: true })).toHaveAttribute("aria-current", "page");
    await page.getByRole("link", { name: "Bibliothek", exact: true }).click();
    await expect(page).toHaveURL(/#planned\/library$/);
    await expect(page.locator("#planLibrarySegment")).toBeVisible();
    await expect(page.locator("#planCalendarSegment")).toBeHidden();
    await expect(page.getByText("Remote-Aktion: Intervals.icu", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Vorschau für Remote-Sync öffnen", exact: true })).toBeVisible();
    await page.getByRole("link", { name: "Ziele & Pläne", exact: true }).click();
    await expect(page).toHaveURL(/#planned\/goals$/);
    await expect(page.locator("#planGoalsSegment")).toBeVisible();
    await expect(page.locator("#planLibrarySegment")).toBeHidden();
    await page.goto("/#planned/goals");
    await expect(page.locator("#planGoalsSegment")).toBeVisible();

    await page.getByRole("link", { name: "Heute", exact: true }).click();
    const checkinButton = page.getByRole("button", { name: /Check-in (ausfüllen|bearbeiten)/ }).first();
    await expect(checkinButton).toBeVisible();
    await checkinButton.click();
    const checkinDialog = page.locator("#checkinDialog");
    await expect(checkinDialog).toBeVisible();
    await expect(checkinDialog.getByRole("heading", { name: "Tages-Check-in" })).toBeVisible();
    await expect(checkinDialog.getByLabel("Tagesform")).toBeVisible();
    await checkinDialog.getByRole("button", { name: "Schließen" }).click();
    await expect(checkinDialog).toBeHidden();

    await page.getByRole("link", { name: "Coach", exact: true }).click();
    const safetyHint = page.getByText("Trainingsempfehlungen dienen zur Orientierung", { exact: false });
    await expect(safetyHint).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("coach-core.png"), fullPage: true });
    await safetyHint.scrollIntoViewIfNeeded();
    await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
    await safetyHint.scrollIntoViewIfNeeded();
    const safetyLayout = await page.evaluate(() => {
      const hint = document.querySelector("#chatPanel .fine-print").getBoundingClientRect();
      const composer = document.querySelector("#chatForm").getBoundingClientRect();
      const navigation = document.querySelector(".bottom-nav").getBoundingClientRect();
      return { hintBottom: hint.bottom, composerTop: composer.top, navigationTop: navigation.top };
    });
    expect(safetyLayout.hintBottom).toBeLessThanOrEqual(Math.min(safetyLayout.composerTop, safetyLayout.navigationTop));
    await page.evaluate(() => { document.documentElement.style.fontSize = ""; });

    await page.goto("/#profile");
    await expect(page.locator("#profilePanel")).toHaveClass(/active/);
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

    for (const [label, panelId] of navigation.filter(([name]) => ["Coach", "Heute", "Mehr"].includes(name))) {
      await page.getByRole("link", { name: label, exact: true }).click();
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
