const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

// #1784: one status strip instead of stacked banners, ranked by severity.
const THRESHOLDS = { stale_after_days: 56, sdk_failure: null, items: [{ label: "FTP Rad", value_text: "250 W", source_label: "Lokal", age_days: 70, reason: "stale" }] };

// Tests use a tall screen unless they check the low-screen layout (under 500 px height).
async function openCoach(page, height = 800) {
  await page.setViewportSize({ width: page.viewportSize().width, height });
  await page.goto("/#coach");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.waitForFunction(() => state.initialStateLoaded);
}

// Sets the notices through the data the real render reads, so a later render keeps them.
async function showNotices(page, { coachError = "Das OpenAI-Guthaben ist aufgebraucht.", thresholds = null } = {}) {
  await page.evaluate(({ coachError: error, thresholds: warnings }) => {
    state.data.sync = { ...state.data.sync, last_error: error };
    state.data.threshold_warnings = warnings;
    renderStatus(state.data);
  }, { coachError, thresholds });
}

test("@responsive offline, a Coach error and the missing Intervals.icu key show one strip", async ({ page, context }) => {
  await openCoach(page);
  await showNotices(page);
  await context.setOffline(true);
  const strip = page.locator("#statusStrip");
  await expect(strip).toBeVisible();
  // Offline explains the rest, so it leads; the Coach error is behind the count.
  await expect(strip.locator(".status-strip-main .status-strip-text")).toContainText("Offline");
  await expect(strip.locator(".status-strip-main .status-strip-text")).not.toContainText("Intervals.icu");
  await expect(strip.locator(".status-strip-more")).toContainText("+1 Hinweis");
  await expect(page.locator(".status-strip:visible")).toHaveCount(1);
  for (const gone of ["#statusCard", "#connectivityNotice", "#providerAttentionBanner", "#setupBanner"]) await expect(page.locator(gone)).toHaveCount(0);
  const box = await strip.boundingBox();
  expect(box.height).toBeLessThanOrEqual(120);
  expect((await new AxeBuilder({ page }).include("#statusStrip").analyze()).violations).toEqual([]);
  await context.setOffline(false);
  await expect(strip.locator(".status-strip-main .status-strip-text")).toContainText("Coach benötigt Aufmerksamkeit");
});

test("@responsive +N Hinweise opens the other notices and closes again", async ({ page, context }) => {
  await openCoach(page);
  await showNotices(page, { thresholds: THRESHOLDS });
  await context.setOffline(true);
  const strip = page.locator("#statusStrip");
  const more = strip.locator(".status-strip-more");
  await expect(more).toContainText("+2 Hinweise");
  await expect(more).toHaveAttribute("aria-expanded", "false");
  await expect(strip.locator("#statusStripList")).toBeHidden();
  await more.click();
  await expect(more).toHaveAttribute("aria-expanded", "true");
  const items = strip.locator("#statusStripList li:visible");
  await expect(items).toHaveCount(2);
  await expect(items.nth(0)).toContainText("Coach benötigt Aufmerksamkeit");
  await expect(items.nth(1)).toContainText("Schwellenwerte prüfen");
  await expect(items.nth(1).getByRole("link", { name: "Prüfen" })).toHaveAttribute("href", "#more/profile");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await more.click();
  await expect(strip.locator("#statusStripList")).toBeHidden();
  await context.setOffline(false);
});

test("@responsive offline names how old the shown data is", async ({ page, context }) => {
  await openCoach(page);
  await page.evaluate(() => { state.dataStandAt = Date.now() - 12 * 60_000; });
  await context.setOffline(true);
  await expect(page.locator("#statusStrip .status-strip-main .status-strip-text")).toContainText("Stand vor 12 min");
  await context.setOffline(false);
});

test("@responsive a stale threshold and a rejected Garmin key are notices of the strip", async ({ page }) => {
  await openCoach(page);
  await showNotices(page, { coachError: null, thresholds: THRESHOLDS });
  const strip = page.locator("#statusStrip");
  await expect(strip).toHaveAttribute("data-level", "warning");
  await expect(strip.locator(".status-strip-main .status-strip-text")).toContainText("FTP Rad 250 W · Lokal · 70 Tage alt");
  await expect(strip).toHaveAttribute("role", "status");
  await page.evaluate(() => renderProviderAttention({ garmin: { personal_api: { configured: true, state: "rejected" } }, provider_freshness: [] }));
  await expect(strip).toHaveAttribute("data-level", "critical");
  await expect(strip).toHaveAttribute("role", "alert");
  await expect(strip.locator(".status-strip-main .status-strip-text")).toContainText("Personal-API-Schlüssel abgelehnt");
  await expect(strip.locator(".status-strip-more")).toContainText("+1 Hinweis");
});

test("@responsive a toast never covers the navigation", async ({ page }) => {
  await page.goto("/#plan/overview");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.waitForFunction(() => state.initialStateLoaded);
  await page.evaluate(() => toast("Aktualisierung fehlgeschlagen", true));
  const toast = page.locator("#toast.show");
  await expect(toast).toBeVisible();
  const toastBox = await toast.boundingBox();
  const bottomNav = page.locator(".bottom-nav");
  if (await bottomNav.isVisible()) {
    expect(toastBox.y + toastBox.height).toBeLessThanOrEqual((await bottomNav.boundingBox()).y);
  } else {
    const nav = await page.locator(".desktop-nav").boundingBox();
    expect(toastBox.x).toBeGreaterThanOrEqual(nav.x + nav.width);
    expect(page.viewportSize().height - (toastBox.y + toastBox.height)).toBeLessThan(40);
  }
});

test("@responsive a low screen keeps the strip to one line and the composer to one row", async ({ page }) => {
  await page.setViewportSize({ width: 844, height: 390 });
  await openCoach(page, 390);
  await showNotices(page, { coachError: null, thresholds: THRESHOLDS });
  const strip = page.locator("#statusStrip");
  const more = strip.locator(".status-strip-more");
  // Warnings only show as a count; the text is behind it.
  await expect(strip.locator(".status-strip-main .status-strip-text")).toBeHidden();
  await expect(more).toHaveText("1 Hinweis", { useInnerText: true });
  expect((await strip.boundingBox()).height).toBeLessThanOrEqual(56);
  await more.click();
  await expect(strip.locator("#statusStripList li:visible")).toHaveCount(1);
  await expect(strip.locator("#statusStripList li .status-strip-text")).toBeVisible();
  await more.click();
  // A critical notice stays readable on one line.
  await showNotices(page, { thresholds: THRESHOLDS });
  const text = strip.locator(".status-strip-main .status-strip-text");
  await expect(text).toBeVisible();
  await expect(text).toContainText("Coach benötigt Aufmerksamkeit");
  expect((await strip.boundingBox()).height).toBeLessThanOrEqual(56);
  const [input, send] = await Promise.all([page.locator("#messageInput").boundingBox(), page.locator("#sendButton").boundingBox()]);
  expect(send.y).toBeLessThan(input.y + input.height);
  expect(send.x).toBeGreaterThan(input.x + input.width - 1);
  const messages = await page.locator("#messages").boundingBox();
  expect(messages.height).toBeGreaterThanOrEqual(100);
});
