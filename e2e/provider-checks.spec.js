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
  await result(page, "openai").locator("xpath=ancestor::article").screenshot({ path: testInfo.outputPath("provider-check.png") });
  providers.openai = { status: "unchecked", checked_at: null };
  await page.evaluate(() => loadProviderChecks());
  await expect(result(page, "openai")).toHaveText("Verbindung: nicht geprüft");
});
