const { test, expect } = require("@playwright/test");

const loads = (page) => page.evaluate(() => Number(sessionStorage.getItem("e2e-loads")));

// Opens the app under a service worker that controlled the page from its load,
// as on every visit after the first, and counts the page loads.
async function controlledApp(page) {
  await page.addInitScript(() => sessionStorage.setItem("e2e-loads", String(Number(sessionStorage.getItem("e2e-loads") || 0) + 1)));
  await page.route("**/api/state/events*", (route) => route.abort());
  await page.goto("/#coach");
  await expect(page.locator("#appShell")).toBeVisible();
  // The first install takes control of the open page without reloading it.
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);
  await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 500)));
  expect(await loads(page)).toBe(1);
  await page.reload();
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator("#messageInput")).toBeVisible();
  expect(await page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);
  expect(await loads(page)).toBe(2);
}

// The event a new worker's skipWaiting and clients.claim cause in the open page.
async function replaceWorker(page) {
  await page.evaluate(() => navigator.serviceWorker.dispatchEvent(new Event("controllerchange")));
}

test("a service worker update keeps a typed draft and reloads once it is cleared", async ({ page }) => {
  await controlledApp(page);
  const input = page.locator("#messageInput");
  await input.fill("Entwurf für später");
  await replaceWorker(page);
  await input.press("End");
  await input.pressSequentially("!");
  await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 500)));
  await expect(input).toHaveValue("Entwurf für später!");
  expect(await loads(page)).toBe(2);
  const reloaded = page.waitForEvent("load");
  await input.fill("");
  await reloaded;
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator("#messageInput")).toHaveValue("");
  expect(await loads(page)).toBe(3);
});

test("a service worker update reloads an idle page once", async ({ page }) => {
  await controlledApp(page);
  const reloaded = page.waitForEvent("load");
  await replaceWorker(page);
  await reloaded;
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator("#authLoading")).toBeHidden();
  await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 500)));
  expect(await loads(page)).toBe(3);
});

async function openProfileForms(page) {
  await page.goto("/#more/profile");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.locator("#zoneSettings > summary").click();
  await expect(page.locator("#zoneLimits")).toBeVisible();
}

async function openYazioForm(page) {
  await page.goto("/#more/connections");
  await expect(page.locator("#appShell")).toBeVisible();
  const section = page.locator('details[data-more-segment-panel="connections"]');
  if (!(await section.evaluate((element) => element.open))) await section.locator("summary").first().click();
  await expect(page.locator("#cred-yazio_email")).toBeVisible();
}

const settle = (page) => page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 500)));

for (const [name, open, field, save, value] of [
  ["zone form", openProfileForms, "#zoneLimits", "#zoneSaveButton", "55 75 90"],
  ["Yazio form", openYazioForm, "#cred-yazio_email", "#cred-submit-yazio", "athlet@example.test"],
]) {
  test(`@responsive a service worker update keeps a typed ${name} value while focus leaves and the save button is pressed`, async ({ page }) => {
    await controlledApp(page);
    await page.route("**/api/zones", (route) => route.fulfill({ status: 400, json: { error: "fixture" } }));
    await page.route("**/api/settings/credentials", (route) => route.fulfill({ status: 400, json: { error: "fixture" } }));
    await open(page);
    const before = await loads(page);
    await page.locator(field).fill(value);
    await replaceWorker(page);
    // Pressing the save button moves focus away first; the click follows the press.
    const box = await page.locator(save).boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await settle(page);
    await expect(page.locator(field)).toHaveValue(value);
    expect(await loads(page)).toBe(before);
    await page.mouse.up();
    await settle(page);
    await expect(page.locator(field)).toHaveValue(value);
    expect(await loads(page)).toBe(before);
  });
}
