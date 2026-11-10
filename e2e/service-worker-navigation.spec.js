const { test, expect } = require("@playwright/test");

async function controlled(page) {
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload();
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);
}

const navigationKeys = (page) => page.evaluate(async () => {
  const [name] = (await caches.keys()).filter((key) => key.startsWith("pacecraft-"));
  const requests = await (await caches.open(name)).keys();
  return requests.map((request) => new URL(request.url).pathname + new URL(request.url).search).filter((key) => !/\.[a-z0-9]+(\?|$)/.test(key));
});

test("@responsive a proxy error page on a navigation shows the cached app shell", async ({ page, context }) => {
  await controlled(page);
  await context.route("**/", (route) => route.request().resourceType() === "document" || route.request().isNavigationRequest()
    ? route.fulfill({ status: 502, contentType: "text/html", body: "<h1>502 Bad Gateway</h1>" })
    : route.fallback());
  await page.reload();
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("502 Bad Gateway");
});

test("@responsive unknown paths and OAuth return URLs add no navigation copies to the cache", async ({ page }) => {
  await controlled(page);
  await page.goto("/does-not-exist");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.goto("/?wahoo=connected");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 500)));
  expect(await navigationKeys(page)).toEqual(["/"]);
});

test("@responsive the manifest icons load and are precached", async ({ page, request }) => {
  await controlled(page);
  const manifest = await (await request.get("/manifest.webmanifest")).json();
  expect(manifest.icons.map((icon) => icon.purpose)).toEqual(["any", "any", "any", "maskable"]);
  for (const icon of manifest.icons) {
    const response = await request.get(icon.src);
    expect(response.ok(), icon.src).toBe(true);
    expect(await page.evaluate(async (src) => Boolean(await caches.match(src, { ignoreSearch: true })), icon.src), icon.src).toBe(true);
  }
});
