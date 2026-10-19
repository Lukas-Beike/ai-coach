const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const AUTH_STATE_PATH = path.join(__dirname, "..", "playwright", ".auth", "user.json");

const LOGIN_ATTEMPTS = 3;
const LOGIN_ATTEMPT_TIMEOUT_MS = 15_000;

// One failed or stalled script request leaves the page without the login form, and Chromium does not refetch it.
// Setup is not under test, so a fresh load is retried instead of failing every spec in the project.
async function openLogin(page) {
  for (let attempt = 1; ; attempt += 1) {
    try {
      await page.goto("/", { timeout: LOGIN_ATTEMPT_TIMEOUT_MS });
      await page.getByLabel("Passwort", { exact: true }).waitFor({ state: "visible", timeout: LOGIN_ATTEMPT_TIMEOUT_MS });
      return;
    } catch (error) {
      if (attempt >= LOGIN_ATTEMPTS) throw error;
      console.warn(`The login form did not appear (attempt ${attempt} of ${LOGIN_ATTEMPTS}); reloading.`);
    }
  }
}

async function authenticate(config) {
  const password = process.env.E2E_APP_PASSWORD;
  if (!password || password.length < 12) {
    throw new Error("E2E_APP_PASSWORD must be set to a fake password of at least 12 characters.");
  }
  const baseURL = config.projects[0]?.use?.baseURL;
  if (!baseURL) throw new Error("The Playwright baseURL is required for E2E authentication.");

  await fs.mkdir(path.dirname(AUTH_STATE_PATH), { recursive: true });
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ baseURL });
    const page = await context.newPage();
    await openLogin(page);
    await page.getByLabel("Passwort", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Anmelden" }).click();
    await page.locator("#loginDialog").waitFor({ state: "hidden" });
    await page.locator("#appShell").waitFor({ state: "visible" });
    await context.storageState({ path: AUTH_STATE_PATH });
    await context.close();
  } finally {
    await browser.close();
  }
}

module.exports = authenticate;
