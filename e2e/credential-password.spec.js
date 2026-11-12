const { test, expect } = require("@playwright/test");
const { expandConnections } = require("./helpers/connections");

// The credential PUT is mocked: no value is stored and no provider is contacted.

async function openCredentials(page) {
  await page.goto("/#more/connections");
  await expect(page.locator("#appShell")).toBeVisible();
  await expandConnections(page, ["openai", "wahoo"]);
  await expect(page.locator("#cred-form-openai")).toBeVisible();
}

test("@responsive changing the OpenAI base URL asks for the app password", async ({ page }) => {
  const bodies = [];
  await page.route("**/api/settings/credentials", (route) => {
    bodies.push(JSON.parse(route.request().postData()));
    return route.fulfill({ json: { fields: {} } });
  });
  await openCredentials(page);
  const passwordRow = page.locator("#cred-password-row-openai");
  await expect(passwordRow).toBeHidden();

  await page.locator("#cred-openai_api_key").fill("sk-fixture-key");
  await expect(passwordRow).toBeHidden();

  await page.locator("#cred-openai_base_url").fill("https://proxy.example.test/v1");
  await expect(passwordRow).toBeVisible();
  await page.locator("#cred-submit-openai").click();
  await expect(page.locator("#cred-error-openai")).toHaveText("Bitte das App-Passwort eingeben.");
  expect(bodies).toEqual([]);

  await page.locator("#cred-app_password-openai").fill("fixture-app-password");
  await page.locator("#cred-submit-openai").click();
  await expect.poll(() => bodies.length).toBe(1);
  expect(bodies[0]).toEqual({
    openai_api_key: "sk-fixture-key",
    openai_base_url: "https://proxy.example.test/v1",
    app_password: "fixture-app-password",
  });
  await expect(page.locator("#cred-app_password-openai")).toHaveValue("");
  await expect(passwordRow).toBeHidden();
  await expect(page.locator("#cred-submit-openai")).toHaveText("Speichern");
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

test("@responsive a wrong app password shows the server message", async ({ page }) => {
  await page.route("**/api/settings/credentials", (route) => route.fulfill({
    status: 403,
    json: { error: "Das App-Passwort fehlt oder ist falsch. Es wurde nichts geändert." },
  }));
  await openCredentials(page);
  await page.locator("#cred-wahoo_client_id").fill("fixture-client");
  await expect(page.locator("#cred-password-row-wahoo")).toBeVisible();
  await page.locator("#cred-app_password-wahoo").fill("wrong-password");
  await page.locator("#cred-submit-wahoo").click();
  await expect(page.locator("#cred-error-wahoo")).toContainText("App-Passwort");
  await expect(page.locator("#cred-app_password-wahoo")).toHaveValue("");
  await expect(page.locator("#cred-submit-wahoo")).toHaveText("Speichern");
  await page.unrouteAll({ behavior: "ignoreErrors" });
});
