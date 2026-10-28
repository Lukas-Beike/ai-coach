const path = require("node:path");
const { defineConfig, devices } = require("@playwright/test");

const authStatePath = process.env.E2E_AUTH_STATE_PATH || path.join(__dirname, "playwright", ".auth", "user.json");

module.exports = defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/auth.setup.js",
  timeout: 60_000,
  expect: { timeout: 30_000 },
  // Keep one worker because the scenarios share and deliberately manipulate fixture data.
  workers: 1,
  forbidOnly: !!process.env.CI,
  // Retries stay on in CI for diagnostics; a test that passes only on retry is reported as failed.
  retries: process.env.CI ? 1 : 0,
  failOnFlakyTests: !!process.env.CI,
  reporter: process.env.CI
    ? [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]]
    : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:8090",
    storageState: authStatePath,
    // CI failure artifacts are public and traces embed the fixture session, so traces stay local.
    trace: process.env.CI ? "off" : "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  // Functional contracts run once; responsive journeys retain every viewport.
  projects: [
    { name: "mobile-small", grep: /@responsive/, use: { ...devices["Pixel 5"], viewport: { width: 320, height: 568 } } },
    { name: "mobile", grep: /@responsive/, use: { ...devices["Pixel 5"], viewport: { width: 390, height: 844 } } },
    { name: "tablet", grep: /@responsive/, use: { ...devices["Desktop Chrome"], viewport: { width: 768, height: 1024 } } },
    { name: "tablet-landscape", grep: /@responsive/, use: { ...devices["Desktop Chrome"], viewport: { width: 844, height: 390 } } },
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
  ],
});
