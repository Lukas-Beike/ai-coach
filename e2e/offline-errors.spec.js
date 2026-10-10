const { test, expect } = require("@playwright/test");
const { captureReadFixture, installReadFixture } = require("./read-fixture");

const TECHNICAL_TEXT = /TypeError|Failed to fetch|network_error|NetworkError/;
const NETWORK_MESSAGE = "Keine Verbindung zum Coach-Server. Prüfe dein Netzwerk und versuche es erneut.";

let fixture;
test.beforeAll(async ({ request }) => { fixture = await captureReadFixture(request); });
test.beforeEach(async ({ page }) => { await installReadFixture(page, fixture); });

async function ready(page) {
  // The SSE transport is irrelevant to these checks; abort it so it does not hold fixture slots.
  await page.route("**/api/state/events*", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => state.loadPromise === null)).toBe(true);
  await expect.poll(() => page.evaluate(() => Boolean(state.data))).toBe(true);
}

test("a failed request without a server response shows an honest German message @responsive", async ({ page }) => {
  await ready(page);
  await page.route("**/api/profile", (route) => (route.request().method() === "PUT"
    ? route.abort("internetdisconnected")
    : route.fallback()));
  await page.evaluate(() => { location.hash = "more/profile"; });
  await expect(page.locator("#profilePanel")).toBeVisible();
  await page.locator("#profileForm button[type=submit]").click();
  const toast = page.locator("#toast");
  await expect(toast).toContainText(NETWORK_MESSAGE);
  await expect(toast).toHaveClass(/error/);
  await expect(toast).not.toContainText(TECHNICAL_TEXT);
  await expect(page.locator("body")).not.toContainText(TECHNICAL_TEXT);
});

test("the offline banner states that changes are not saved and promises no later delivery @responsive", async ({ page, context }) => {
  await ready(page);
  const notice = page.locator("#connectivityNotice");
  await context.setOffline(true);
  await expect(notice).toBeVisible();
  await expect(notice).toHaveText("Offline – Änderungen können gerade nicht gespeichert werden. Bereits geladene Daten bleiben sichtbar.");
  await expect(notice).not.toContainText(/warten|gesendet|sp[äa]ter|Warteschlange/i);
  await context.setOffline(false);
  await expect(notice).toBeHidden();
});

test("stale provider data is a polite status while real provider errors stay alerts @responsive", async ({ page }) => {
  await ready(page);
  const banner = page.locator("#providerAttentionBanner");
  await page.evaluate(() => renderProviderAttention({
    provider_freshness: [{ configured: true, state: "stale", label: "Garmin" }],
  }));
  await expect(banner).toBeVisible();
  await expect(banner).toHaveAttribute("role", "status");
  await expect(banner).toHaveAttribute("aria-live", "polite");
  await page.evaluate(() => renderProviderAttention({
    provider_freshness: [{ configured: true, state: "error", error_code: "auth_required", label: "Intervals.icu" }],
  }));
  await expect(banner).toHaveAttribute("role", "alert");
  await expect(banner).toHaveAttribute("aria-live", "assertive");
});
