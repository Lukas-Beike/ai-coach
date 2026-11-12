const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;
const { contrastRatio } = require("./helpers/ui");
const { expandConnections } = require("./helpers/connections");

// #1788: touch-friendly sports chips, text status per connection, structured profile.

async function openMore(page, segment) {
  await page.goto(`/#more/${segment}`);
  await expect(page.locator("#appShell")).toBeVisible();
  await page.waitForFunction(() => state.initialStateLoaded);
}

test("@responsive sports are toggle chips of at least 44 px and need no hint", async ({ page }) => {
  await openMore(page, "profile");
  // Every profile section starts closed (#2262).
  await page.locator("#profileForm > details.profile-section").first().locator(":scope > summary").click();
  const chips = page.locator("#profileForm .chip-field .chip");
  await expect(chips).toHaveCount(6);
  for (const chip of await chips.all()) expect((await chip.locator("span").boundingBox()).height).toBeGreaterThanOrEqual(44);
  await expect(page.locator("#profileForm")).not.toContainText("Strg");
  const running = chips.filter({ hasText: "Laufen" });
  const box = running.locator("input");
  const before = await box.isChecked();
  await running.click();
  expect(await box.isChecked()).toBe(!before);
  await expect(page.locator("#profileDirtyIndicator")).toBeVisible();
  // H-201: leaving the dirty profile for another "Mehr" segment asks first.
  await page.evaluate(() => { location.hash = "#more/connections"; });
  await expect(page.locator("#confirmationDialog")).toBeVisible();
  await page.locator("#confirmationDialogCancel").click();
  await expect(page.locator("#profilePanel")).toBeVisible();
  await expect(page).toHaveURL(/#more\/profile$/);
  expect(await box.isChecked()).toBe(!before);
  const saved = page.waitForResponse((response) => response.url().endsWith("/api/profile") && response.request().method() === "PUT");
  await page.getByRole("button", { name: "Athletenkontext speichern" }).click();
  const request = (await saved).request().postDataJSON();
  expect(request.sports.includes("Running")).toBe(!before);
  await expect(page.locator(".save-clean")).toBeVisible();
  await expect(page.locator("#profileDirtyIndicator")).toBeHidden();
});

test("@responsive the profile has five closed summarised sections and a save bar that stays in view", async ({ page }) => {
  await openMore(page, "profile");
  const sections = page.locator("#profileForm > details.profile-section");
  await expect(sections).toHaveCount(5);
  // Every section starts closed (#2262); the zone summary is empty without a stale threshold.
  for (const section of await sections.all()) await expect(section).not.toHaveAttribute("open", "");
  for (const summary of await sections.locator("> summary .collapsible-summary-meta:not(#zoneSummary)").all()) expect((await summary.textContent()).trim()).not.toBe("");
  await sections.evaluateAll((nodes) => nodes.forEach((node) => { node.open = true; }));
  await page.getByLabel("Name", { exact: true }).fill("Fixture Athlete");
  await page.evaluate(() => window.scrollTo(0, 0));
  const bar = page.locator(".save-bar");
  await expect(bar).toBeInViewport({ ratio: 1 });
  await expect(page.locator("#profileDirtyIndicator")).toHaveText("Ungespeichert");
  const barBox = await bar.boundingBox();
  const nav = page.locator(".bottom-nav");
  if (await nav.isVisible()) expect(barBox.y + barBox.height).toBeLessThanOrEqual((await nav.boundingBox()).y);
  for (const textarea of await page.locator("#profileForm textarea:visible").all()) {
    expect(await textarea.evaluate((node) => getComputedStyle(node).resize)).toBe("none");
  }
});

test("@responsive a closed profile section opens when it holds the invalid value", async ({ page }) => {
  await openMore(page, "profile");
  const sources = page.locator("#profileForm > details.profile-section").nth(4);
  await expect(sources).not.toHaveAttribute("open", "");
  await sources.evaluate((node) => { node.querySelector('[name="sleep_target_hours"]').value = "99"; });
  await page.locator("#profileForm").evaluate((form) => form.dispatchEvent(new Event("input", { bubbles: true })));
  await page.getByRole("button", { name: "Athletenkontext speichern" }).click();
  await expect(sources).toHaveAttribute("open", "");
});

test("@responsive Mehr keeps its title and shows the active area and fits all six items without scrolling", async ({ page }) => {
  for (const segment of ["profile", "connections", "operations"]) {
    await openMore(page, segment);
    const panel = page.locator(".panel.active");
    await expect(panel.getByRole("heading", { level: 2 })).toHaveText("Mehr");
    const nav = panel.locator(".more-segment-nav");
    const active = nav.locator("a.active");
    await expect(active).toHaveCount(1);
    const colors = await active.evaluate((node) => ({ color: getComputedStyle(node).color, background: getComputedStyle(node).backgroundColor }));
    expect(contrastRatio(colors.color, colors.background)).toBeGreaterThanOrEqual(4.5);
    const navBox = await nav.boundingBox();
    const activeBox = await active.boundingBox();
    expect(activeBox.x).toBeGreaterThanOrEqual(navBox.x - 1);
    expect(activeBox.x + activeBox.width).toBeLessThanOrEqual(navBox.x + navBox.width + 1);
    if (page.viewportSize().width < 1100) {
      expect(await nav.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
      const links = nav.locator("a");
      await expect(links).toHaveCount(6);
      for (const link of await links.all()) {
        await expect(link).toBeInViewport();
        const box = await link.boundingBox();
        expect(box.x).toBeGreaterThanOrEqual(navBox.x - 1);
        expect(box.x + box.width).toBeLessThanOrEqual(navBox.x + navBox.width + 1);
        expect(box.height).toBeGreaterThanOrEqual(44);
      }
    }
  }
});

test("@responsive the eight connections start collapsed and name their status in words", async ({ page }) => {
  await openMore(page, "connections");
  const cards = page.locator(".connection-cards > details.connection-card");
  await expect(cards.locator("summary strong")).toHaveText(["Garmin", "Wahoo", "Intervals.icu", "OpenAI", "Claude (Anthropic)", "Yazio", "Gemeinsamer Kalender", "Open-Meteo"]);
  await expect(page.locator(".connection-card[open]")).toHaveCount(0);
  for (const card of await cards.all()) await expect(card.locator(".connection-card-body")).toBeHidden();
  const chips = cards.locator("summary .connection-chip");
  await expect(chips).toHaveCount(8);
  await expect(page.locator(".connection-cards .connection-chip:not([data-state])")).toHaveCount(0);
  for (const chip of await chips.all()) expect(["Verbunden", "Nicht eingerichtet", "Fehler", "Nicht geprüft"]).toContain((await chip.textContent()).trim());
  await expect(page.locator("#providerCredentials, #providerFreshnessTimeline, #connectionsSummary")).toHaveCount(0);
  await expandConnections(page, ["garmin"]);
  const lines = page.locator("#garminSourceLines li");
  await expect(lines).toHaveCount(2);
  await expect(lines.nth(0)).toContainText("Personal API:");
  await expect(lines.nth(1)).toContainText("SDK-Login:");
});

test("@responsive an open card holds only its own provider's status, access, settings and actions", async ({ page }) => {
  await openMore(page, "connections");
  await expandConnections(page, ["garmin"]);
  const garmin = page.locator("#connection-garmin");
  for (const selector of ["#garminSourceLines", "#freshness-garmin", "#garmin-connection-status", "#cred-garmin_personal_api_key", "#cred-garmin_personal_api_key_expires", "#garmin-metric-export", "#garminSyncButton", "[data-check-button='garmin']"]) {
    await expect(garmin.locator(selector)).toHaveCount(1);
  }
  await expect(garmin.locator("[id*='openai'], [id*='anthropic'], [id*='wahoo'], [id*='intervals_'], [id*='yazio']")).toHaveCount(0);
  await expect(page.locator("#connection-wahoo .connection-card-body")).toBeHidden();
  await expect(page.locator("#connection-weather a[href='https://open-meteo.com/']")).toHaveText("Open-Meteo.com");
  await expandConnections(page, ["wahoo"]);
  await expect(page.locator(".connection-card[open]")).toHaveCount(2);
});

test("@responsive collapsible sections share one chevron and the page passes the contrast check", async ({ page }) => {
  await openMore(page, "connections");
  const summary = page.locator("#connection-garmin > summary");
  expect(await summary.evaluate((node) => getComputedStyle(node, "::after").content)).not.toBe("none");
  expect(await summary.evaluate((node) => getComputedStyle(node).listStyleType)).toBe("none");
  await expandConnections(page);
  for (const segment of ["connections", "profile"]) {
    await page.goto(`/#more/${segment}`);
    const results = await new AxeBuilder({ page }).include(".panel.active").withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(results.violations, `${segment} accessibility violations`).toEqual([]);
  }
});
