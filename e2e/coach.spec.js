const { test, expect } = require("@playwright/test");
const { AxeBuilder } = require("@axe-core/playwright");

const APP_PASSWORD = process.env.E2E_APP_PASSWORD;
if (!APP_PASSWORD || APP_PASSWORD.length < 12) {
  throw new Error("E2E_APP_PASSWORD must be set to a fake password of at least 12 characters.");
}

const navigation = [
  ["Coach", "chatPanel", "coach"],
  ["Heute", "todayPanel", "today"],
  ["Plan", "workoutsPanel", "plan/calendar"],
  ["Analyse", "dataPanel", "analysis/history"],
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

    await page.getByRole("link", { name: "Analyse", exact: true }).click();
    await expect(page).toHaveURL(/#analysis\/history$/);
    await page.getByRole("link", { name: "Leistung", exact: true }).click();
    await expect(page).toHaveURL(/#analysis\/performance$/);
    await page.goBack();
    await expect(page.locator("#dataPanel")).toHaveClass(/active/);
    await expect(page).toHaveURL(/#analysis\/history$/);
    await page.getByRole("link", { name: "Mehr", exact: true }).click();
    await expect(page.locator("#settingsPanel")).toHaveClass(/active/);
    await expect(page).toHaveURL(/#more$/);
    await page.goto("/#analysis/performance");
    await expect(page.locator("#dataPanel")).toHaveClass(/active/);
    await expect(page).toHaveURL(/#analysis\/performance$/);
    await page.goto("/#unknown-route");
    await expect(page.locator("#chatPanel")).toHaveClass(/active/);
    await expect(page).toHaveURL(/#coach$/);

    const settingsNav = page.locator("#settingsPanel .more-segment-nav");
    await page.getByRole("link", { name: "Mehr", exact: true }).click();
    await expect(page).toHaveURL(/#more$/);
    await expect(page.locator('[data-more-segment-panel="connections"]').first()).toBeVisible();
    await page.getByRole("link", { name: "Coach & Modell", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#more\/coach$/);
    await page.getByRole("link", { name: "Mehr", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#more$/);
    await settingsNav.getByRole("link", { name: "Coach & Modell", exact: true }).click();
    await expect(page).toHaveURL(/#more\/coach$/);
    await expect(page.locator('[data-more-segment-panel="coach"]')).toHaveCount(2);
    await expect(page.locator('[data-more-segment-panel="coach"]').first()).toBeVisible();
    await expect(page.locator('[data-more-segment-panel="connections"]').first()).toBeHidden();
    await settingsNav.getByRole("link", { name: "Daten & Datenschutz", exact: true }).click();
    await expect(page).toHaveURL(/#more\/privacy$/);
    await expect(page.locator('[data-more-segment-panel="privacy"]')).toBeVisible();
    await settingsNav.getByRole("link", { name: "Betrieb & Diagnose", exact: true }).click();
    await expect(page).toHaveURL(/#more\/operations$/);
    await expect(page.locator('[data-more-segment-panel="operations"]').first()).toBeVisible();
    await settingsNav.getByRole("link", { name: "Athletenprofil", exact: true }).click();
    await expect(page).toHaveURL(/#more\/profile$/);
    await expect(page.locator("#profilePanel")).toHaveClass(/active/);
    await expect(page.locator("#profileContextNotice")).toBeVisible();

    await page.getByRole("link", { name: "Plan", exact: true }).click();
    await expect(page.locator("#planCalendarSegment")).toBeVisible();
    await expect(page.getByRole("link", { name: "Kalender", exact: true })).toHaveAttribute("aria-current", "page");
    await page.getByRole("link", { name: "Bibliothek", exact: true }).click();
    await expect(page).toHaveURL(/#plan\/templates$/);
    await expect(page.locator("#planLibrarySegment")).toBeVisible();
    await expect(page.locator("#planCalendarSegment")).toBeHidden();
    await expect(page.getByText("Lokal speichern · Remote-Sync nur mit Vorschau", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Vorschau für Bibliotheks- und Planungssync", exact: true })).toBeVisible();
    await page.getByRole("link", { name: "Ziele & Pläne", exact: true }).click();
    await expect(page).toHaveURL(/#plan\/goals$/);
    await expect(page.locator("#planGoalsSegment")).toBeVisible();
    await expect(page.locator("#planLibrarySegment")).toBeHidden();
    await page.goto("/#planned/goals");
    await expect(page.locator("#planGoalsSegment")).toBeVisible();
    await expect(page).toHaveURL(/#plan\/goals$/);

    await page.getByRole("link", { name: "Heute", exact: true }).click();
    await expect(page.getByRole("button", { name: /Check-in (ausfüllen|prüfen)/ })).toBeVisible();
    await expect(page.locator("#checkinDialog")).toBeHidden();
    await expect(page.locator("#chatPanel")).toContainText("Morgen-Check-in");

    const undersizedTargets = await page.locator(".panel.active button:visible, .panel.active a:visible, .panel.active input:visible, .panel.active textarea:visible, .panel.active select:visible, .panel.active summary:visible, .bottom-nav a:visible").evaluateAll((nodes) => nodes
      .filter((node) => !node.closest("[hidden]"))
      .filter((node) => node.getBoundingClientRect().width < 44 || node.getBoundingClientRect().height < 44)
      .map((node) => ({ tag: node.tagName, id: node.id, text: node.textContent.trim().slice(0, 40) })));
    expect(undersizedTargets, "visible touch targets below 44 CSS pixels").toEqual([]);

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
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.getByRole("link", { name: "Heute", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("#todayPanel")).toHaveClass(/active/);

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
