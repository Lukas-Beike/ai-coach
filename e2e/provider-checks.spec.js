const { test, expect } = require("@playwright/test");
const { expandConnections } = require("./helpers/connections");

const result = (page, provider) => page.locator(`[data-check-result="${provider}"]`);
const button = (page, provider) => page.locator(`[data-check-button="${provider}"]`);

test("@responsive provider cards run an explicit check and keep it separate from sync labels", async ({ page }, testInfo) => {
  const providers = {
    openai: { status: "unchecked", checked_at: null },
    intervals: { status: "unchecked", checked_at: null },
    garmin: { status: "not_configured", checked_at: null },
    wahoo: { status: "not_configured", checked_at: null },
    weather: { status: "unchecked", checked_at: null },
  };
  const checks = [];
  await page.route("**/api/providers/connections", (route) => route.fulfill({ json: { providers } }));
  await page.route("**/api/providers/*/check", (route) => {
    const provider = route.request().url().split("/").at(-2);
    checks.push(provider);
    providers[provider] = provider === "intervals"
      ? { status: "auth_failed", checked_at: "2026-01-01T12:00:00Z", guidance: "Anmeldung abgelehnt – API-Schlüssel und Athlete-ID prüfen" }
      : { status: "success", checked_at: "2026-01-01T12:00:00Z" };
    return route.fulfill({ json: providers[provider] });
  });
  await page.goto("/#more/connections");
  await expect(page.locator("#appShell")).toBeVisible();
  await expandConnections(page);
  await expect(result(page, "openai")).toHaveText("Verbindung: nicht geprüft");
  await expect(button(page, "garmin")).toBeDisabled();
  await button(page, "openai").click();
  await expect(result(page, "openai")).toContainText("Verbindung erfolgreich");
  await button(page, "intervals").click();
  await expect(result(page, "intervals")).toContainText("Anmeldung abgelehnt");
  expect(checks).toEqual(["openai", "intervals"]);
  await result(page, "openai").locator("xpath=ancestor::details[1]").screenshot({ path: testInfo.outputPath("provider-check.png") });
  providers.openai = { status: "unchecked", checked_at: null };
  await page.evaluate(() => loadProviderChecks());
  await expect(result(page, "openai")).toHaveText("Verbindung: nicht geprüft");
});

test("@responsive Intervals.icu shows the server's last export after a reload and checks nothing", async ({ page }) => {
  let intervals = { configured: true, state: "configured", running: false, last_error: null, last_used_at: null, library_sync: { last_sync_at: null, state: {} } };
  const posts = [];
  await page.route("**/api/bootstrap**", async (route) => {
    const response = await route.fetch();
    return route.fulfill({ json: { ...(await response.json()), intervals } });
  });
  await page.route("**/api/providers/connections", (route) => route.fulfill({ json: { providers: { intervals: { status: "unchecked", checked_at: null } } } }));
  page.on("request", (request) => { if (request.method() === "POST") posts.push(request.url()); });
  await page.goto("/#more/connections");
  await expect(page.locator("#appShell")).toBeVisible();
  await expandConnections(page, ["intervals"]);
  await expect(page.locator("#intervalsConnectionStatus")).toHaveText("Nicht geprüft");
  // The plan export of the week succeeded: connected without a library sync or a check.
  intervals = { ...intervals, state: "connected", last_used_at: "2026-09-01T08:00:00+00:00" };
  await page.reload();
  await expandConnections(page, ["intervals"]);
  await expect(page.locator("#intervalsConnectionStatus")).toHaveText("Verbunden");
  await expect(page.locator("#intervalsConnectionDetail")).toContainText("Letzte Aktualisierung");
  intervals = { ...intervals, state: "error" };
  await page.reload();
  await expandConnections(page, ["intervals"]);
  await expect(page.locator("#intervalsConnectionStatus")).toHaveText("Fehler");
  await expect(page.locator("#intervalsConnectionDetail")).toHaveText("Letzter Export fehlgeschlagen");
  expect(posts.filter((url) => url.includes("/check"))).toEqual([]);
});
