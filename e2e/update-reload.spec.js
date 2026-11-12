const { test, expect } = require("@playwright/test");
const { expandConnections } = require("./helpers/connections");

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
  // #2262: a zone kind's "Bearbeiten"/"Anlegen" opens the editor under it.
  await page.locator('#zoneOverview [data-zone-box="power"] .zone-edit').click();
  await expect(page.locator("#zoneLimits")).toBeVisible();
  // The fixture has no FTP to prefill, and the power editor needs one.
  await page.locator("#zoneThreshold").fill("250");
}

async function openYazioForm(page) {
  await page.goto("/#more/connections");
  await expect(page.locator("#appShell")).toBeVisible();
  await expandConnections(page, ["yazio"]);
  await expect(page.locator("#cred-yazio_email")).toBeVisible();
}

const settle = (page) => page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 500)));

// The press reaches the save: the rejected zone form keeps its value, the credential
// form shows the server error and is emptied, so no credential lingers in the DOM.
const zoneSaved = async (page, field, value) => {
  await expect(page.locator("#toast")).toContainText("fixture");
  await expect(page.locator(field)).toHaveValue(value);
};
const credentialSaved = async (page, field) => {
  await expect(page.locator("#cred-error-yazio")).toHaveText("fixture");
  await expect(page.locator(field)).toHaveValue("");
};

for (const [name, open, field, save, value, saved] of [
  ["zone form", openProfileForms, "#zoneLimits", "#zoneSaveButton", "55 75 90", zoneSaved],
  ["Yazio form", openYazioForm, "#cred-yazio_email", "#cred-submit-yazio", "athlet@example.test", credentialSaved],
]) {
  test(`@responsive a service worker update keeps a typed ${name} value while focus leaves and the save button is pressed`, async ({ page }) => {
    await controlledApp(page);
    await page.route("**/api/zones", (route) => (route.request().method() === "GET" ? route.fallback() : route.fulfill({ status: 400, json: { error: "fixture" } })));
    await page.route("**/api/settings/credentials", (route) => route.fulfill({ status: 400, json: { error: "fixture" } }));
    await open(page);
    const before = await loads(page);
    await page.locator(field).fill(value);
    await replaceWorker(page);
    // Pressing the save button moves focus away first; the click follows the press.
    // Centred, so the press cannot land on the fixed navigation instead.
    await page.locator(save).evaluate((button) => button.scrollIntoView({ block: "center" }));
    const box = await page.locator(save).boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await settle(page);
    await expect(page.locator(field)).toHaveValue(value);
    expect(await loads(page)).toBe(before);
    await page.mouse.up();
    await settle(page);
    await saved(page, field, value);
    expect(await loads(page)).toBe(before);
  });
}
