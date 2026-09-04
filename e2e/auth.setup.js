const fs = require("node:fs/promises");
const path = require("node:path");
const { chromium } = require("@playwright/test");

const AUTH_STATE_PATH = path.join(__dirname, "..", "playwright", ".auth", "user.json");

module.exports = async (config) => {
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
    await page.goto("/");
    await page.getByLabel("Passwort").fill(password);
    await page.getByRole("button", { name: "Anmelden" }).click();
    await page.locator("#loginDialog").waitFor({ state: "hidden" });
    await page.locator("#appShell").waitFor({ state: "visible" });
    await context.storageState({ path: AUTH_STATE_PATH });
    await context.close();
  } finally {
    await browser.close();
  }
};
