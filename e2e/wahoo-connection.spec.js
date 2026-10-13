const { test, expect } = require("@playwright/test");

// The disposable fixture has no Wahoo credentials. Configured and connected
// states are produced by rewriting the bootstrap JSON; no real account, token
// or provider request is involved.

const FAKE_AUTHORIZE_URL = "https://wahoo.example.test/oauth/authorize?state=fixture";

async function withWahooState(page, wahoo, extra = {}) {
  await page.route("**/api/bootstrap*", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.wahoo = wahoo;
    Object.assign(body, extra(body));
    await route.fulfill({ response, json: body });
  });
}

async function openConnections(page, url = "/#more/connections") {
  await page.goto(url);
  await expect(page.locator("#appShell")).toBeVisible();
  const section = page.locator('details[data-more-segment-panel="connections"]');
  await expect(section).toBeVisible();
  if (!(await section.evaluate((element) => element.open))) await section.locator("summary").first().click();
  await expect(page.locator("#wahooConnectionStatus")).not.toHaveText("Status wird geprüft…");
  return page.locator("#wahooConnectionStatus").locator("xpath=ancestor::article");
}

test("@responsive Wahoo without server credentials explains the missing configuration", async ({ page }) => {
  const card = await openConnections(page);
  await expect(page.locator("#wahooConnectionStatus")).toHaveText("Nicht konfiguriert");
  await expect(page.locator("#wahooSetupHint")).toContainText("WAHOO_CLIENT_ID");
  await expect(page.locator("#wahooConnectButton")).toBeHidden();
  await expect(page.locator("#wahooDisconnectButton")).toBeHidden();
  await card.scrollIntoViewIfNeeded();
  await card.screenshot({ path: "test-results/wahoo-not-configured.png" });
});

test("@responsive configured Wahoo offers Connect and follows the authorize URL", async ({ page }) => {
  await withWahooState(page, { configured: true, connected: false, scope: null, connected_at: null }, () => ({}));
  await page.route("**/api/wahoo/connect", (route) => route.fulfill({ json: { authorize_url: FAKE_AUTHORIZE_URL } }));
  await page.route("https://wahoo.example.test/**", (route) => route.fulfill({ contentType: "text/html", body: "<title>fake wahoo</title>" }));
  const card = await openConnections(page);
  await expect(page.locator("#wahooConnectionStatus")).toHaveText("Nicht verbunden");
  await expect(page.locator("#wahooSetupHint")).toBeHidden();
  await expect(page.locator("#wahooDisconnectButton")).toBeHidden();
  await card.scrollIntoViewIfNeeded();
  await card.screenshot({ path: "test-results/wahoo-configured.png" });
  await page.locator("#wahooConnectButton").click();
  await expect(page).toHaveURL(FAKE_AUTHORIZE_URL);
});

test("@responsive a rejected Wahoo token asks for a reconnect", async ({ page }) => {
  await withWahooState(page, { configured: true, connected: false, scope: null, connected_at: null }, (body) => ({
    provider_freshness: [...(body.provider_freshness || []), { provider: "wahoo", label: "Wahoo", area: "activities", state: "error", error_code: "auth_required", configured: true }],
  }));
  await openConnections(page);
  await expect(page.locator("#wahooConnectionStatus")).toHaveText("Erneute Verbindung erforderlich");
  await expect(page.locator("#wahooConnectButton")).toHaveText("Wahoo erneut verbinden");
});

test("@responsive connected Wahoo shows its label everywhere and can be disconnected", async ({ page }) => {
  let disconnected = false;
  await withWahooState(page, { configured: true, connected: true, scope: "workouts_read", connected_at: "2026-01-02T08:00:00+00:00" }, (body) => ({
    provider_labels: { ...body.provider_labels, wahoo: "Wahoo" },
    provider_freshness: [...(body.provider_freshness || []), { provider: "wahoo", label: "Wahoo", area: "activities", state: "fresh", configured: true }],
  }));
  await page.route("**/api/wahoo/disconnect", (route) => {
    disconnected = true;
    return route.fulfill({ json: { status: "ok", connected: false, remote_revoked: true } });
  });
  const card = await openConnections(page);
  await expect(page.locator("#wahooConnectionStatus")).toHaveText("Verbunden");
  await expect(page.locator("#wahooConnectionDetail")).toContainText("Verbunden seit");
  await expect(page.locator("#connectionsSummary")).toContainText("Wahoo ✓");
  await expect(page.locator("#providerFreshnessTimeline")).toContainText("Wahoo");
  await expect(page.locator("#wahooConnectButton")).toBeHidden();
  await expect(card).not.toContainText("workouts_read");
  await card.scrollIntoViewIfNeeded();
  await card.screenshot({ path: "test-results/wahoo-connected.png" });
  await page.locator("#wahooDisconnectButton").click();
  await page.locator("#confirmationDialog").locator("#confirmationDialogAccept").click();
  await expect.poll(() => disconnected).toBe(true);
  await expect(page.locator("#toast")).toContainText("Wahoo getrennt");
  // Let the follow-up state reload settle before the routes are torn down.
  await page.waitForLoadState("networkidle");
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

test("@responsive the OAuth return outcome is announced once and removed from the address", async ({ page }) => {
  await openConnections(page, "/?wahoo=connected#more/connections");
  await expect(page.locator("#toast")).toContainText("Wahoo verbunden");
  expect(new URL(page.url()).search).toBe("");
});
