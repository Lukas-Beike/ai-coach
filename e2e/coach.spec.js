const { test, expect } = require("@playwright/test");
const { AxeBuilder } = require("@axe-core/playwright");

const APP_PASSWORD = process.env.E2E_APP_PASSWORD;
if (!APP_PASSWORD || APP_PASSWORD.length < 12) {
  throw new Error("E2E_APP_PASSWORD must be set to a fake password of at least 12 characters.");
}

const navigation = [
  ["Coach", "chatPanel", "coach"],
  ["Heute", "todayPanel", "today"],
  ["Bibliothek", "workoutsPanel", "plan"],
  ["Analyse", "dataPanel", "analysis/performance"],
  ["Mehr", "settingsPanel", "more"],
];

async function login(page) {
  await page.goto("/");
  const loginDialog = page.locator("#loginDialog");
  await expect(loginDialog).toBeVisible();
  await page.getByLabel("Passwort").fill(APP_PASSWORD);
  await page.getByRole("button", { name: "Anmelden" }).click();
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
    await expect(page.locator("#loginDialog")).toBeHidden();
    await expect(page.locator("#appShell")).toBeVisible();
    await expect(page.locator("#profilePanel")).toHaveClass(/active/);
    await expect(page).toHaveURL(/#more\/profile$/);
    await expect(page.locator("#profilePanel")).toBeFocused();
    await expect(page.locator(".dirty-indicator")).toHaveCount(3);
    const hiddenIndicators = await page.locator(".dirty-indicator").evaluateAll((nodes) => nodes.every((node) => node.hidden));
    expect(hiddenIndicators).toBe(true);
    await expect(page.locator("#remoteDeleteNotice")).toHaveCount(0);
    for (const [label, panelId, route] of navigation) {
      await page.getByRole("link", { name: label, exact: true }).click();
      await expect(page.locator(`#${panelId}`)).toHaveClass(/active/);
      await expect(page.getByRole("link", { name: label, exact: true })).toHaveAttribute("aria-current", "page");
      await expect(page.getByRole("link", { name: label, exact: true })).toHaveAttribute("href", `#${route}`);
    }

    await page.getByRole("link", { name: "Analyse", exact: true }).click();
    await expect(page).toHaveURL(/#analysis\/performance$/);
    await page.getByRole("link", { name: "Verlauf", exact: true }).click();
    await expect(page).toHaveURL(/#analysis\/history$/);
    await page.goBack();
    await expect(page.locator("#dataPanel")).toHaveClass(/active/);
    await expect(page).toHaveURL(/#analysis\/performance$/);
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

    await page.getByRole("link", { name: "Bibliothek", exact: true }).click();
    await expect(page).toHaveURL(/#plan$/);
    await expect(page.getByRole("heading", { name: "Bibliothek", exact: true })).toBeVisible();
    await expect(page.locator("#libraryLoadButton, #libraryFilter, #librarySelectVisibleButton, #librarySyncSelectedButton")).toHaveCount(0);
    await page.goto("/#planned/goals");
    await expect(page.locator("#workoutsPanel")).toHaveClass(/active/);
    await expect(page).toHaveURL(/#plan$/);

    await page.getByRole("link", { name: "Heute", exact: true }).click();
    await expect(page.locator("#todayPanel .today-priority")).toContainText("Coach-Einordnung");
    await expect(page.locator("#todayPanel .today-checkin")).toContainText("Morgen-Check-in");
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
      const navigationNode = document.querySelector(".bottom-nav");
      const navigation = navigationNode && getComputedStyle(navigationNode).display !== "none"
        ? navigationNode.getBoundingClientRect()
        : null;
      return { hintBottom: hint.bottom, composerTop: composer.top, navigationTop: navigation?.top ?? Number.POSITIVE_INFINITY };
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

    for (const [label, panelId] of navigation) {
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

  test("inactive panels stay hidden and compact labels remain readable", async ({ page }) => {
    const browserErrors = installBrowserGuards(page);
    await login(page);
    await page.getByRole("link", { name: "Coach", exact: true }).click();
    const panelState = await page.locator("main .panel").evaluateAll((panels) => panels.map((panel) => ({
      id: panel.id,
      active: panel.classList.contains("active"),
      display: getComputedStyle(panel).display,
    })));
    expect(panelState.filter((panel) => !panel.active && panel.display !== "none"), "inactive panels must not leak into the active view").toEqual([]);
    const clippedLabels = await page.locator(".coach-provider-item strong:visible").evaluateAll((nodes) => nodes
      .filter((node) => node.scrollWidth > node.clientWidth || node.getBoundingClientRect().right > window.innerWidth + 1)
      .map((node) => node.textContent));
    expect(clippedLabels, "visible provider labels must fit their cards").toEqual([]);
    await expectNoBrowserErrorsOrOverflow(page, browserErrors);
  });

});
