const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    window.testEventSources = [];
    window.EventSource = class {
      constructor() { this.closed = false; window.testEventSources.push(this); }
      addEventListener() {}
      close() { this.closed = true; }
    };
  });
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.testEventSources.length)).toBe(1);
  await page.clock.install({ time: new Date("2026-09-08T12:00:00Z") });
  await page.clock.pauseAt(new Date("2026-09-08T12:00:01Z"));
});

test("short-lived status connections back off while logs and diagnostics stay usable", async ({ page }) => {
  for (const [index, delay] of [1000, 2000, 4000, 8000, 16000, 30000, 30000].entries()) {
    await page.evaluate(() => {
      const source = window.testEventSources.at(-1);
      source.onopen();
      source.onerror();
    });
    expect(await page.evaluate(() => window.testEventSources.at(-1).closed)).toBe(true);
    await page.clock.runFor(delay - 1);
    expect(await page.evaluate(() => window.testEventSources.length)).toBe(index + 1);
    await page.clock.runFor(1);
    expect(await page.evaluate(() => window.testEventSources.length)).toBe(index + 2);
  }
  const result = await page.evaluate(async () => {
    await loadLogs();
    const capture = await AppApi.request("/api/diagnostics/capture", { method: "POST", body: '{"enabled":true}' });
    return { logs: document.querySelector("#logsOutput").textContent, capture: capture.active };
  });
  expect(result.logs).not.toContain("NetworkError");
  expect(result.capture).toBe(true);
  // Only a sustained connection restores the initial retry interval.
  await page.evaluate(() => window.testEventSources.at(-1).onopen());
  await page.clock.runFor(30000);
  await page.evaluate(() => window.testEventSources.at(-1).onerror());
  await page.clock.runFor(999);
  expect(await page.evaluate(() => window.testEventSources.length)).toBe(8);
  await page.clock.runFor(1);
  expect(await page.evaluate(() => window.testEventSources.length)).toBe(9);
});

test("hidden and offline pages release status streams and resume only one connection", async ({ page }) => {
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  expect(await page.evaluate(() => window.testEventSources[0].closed)).toBe(true);
  await page.clock.runFor(31000);
  expect(await page.evaluate(() => window.testEventSources.length)).toBe(1);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event("pageshow"));
  });
  expect(await page.evaluate(() => window.testEventSources.length)).toBe(2);
  await page.evaluate(() => {
    window.testEventSources.at(-1).onopen();
    window.testEventSources.at(-1).onerror();
    Object.defineProperty(navigator, "onLine", { configurable: true, value: false });
    window.dispatchEvent(new Event("offline"));
  });
  await page.clock.runFor(31000);
  expect(await page.evaluate(() => window.testEventSources.length)).toBe(2);
  await page.evaluate(() => {
    Object.defineProperty(navigator, "onLine", { configurable: true, value: true });
    window.dispatchEvent(new Event("online"));
    window.dispatchEvent(new Event("online"));
  });
  expect(await page.evaluate(() => window.testEventSources.length)).toBe(3);
  await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
  expect(await page.evaluate(() => window.testEventSources.at(-1).closed)).toBe(true);
  await page.evaluate(() => window.dispatchEvent(new Event("pageshow")));
  expect(await page.evaluate(() => window.testEventSources.length)).toBe(4);
  // A queued error from an obsolete connection cannot close the new one.
  await page.evaluate(() => window.testEventSources[0].onerror());
  expect(await page.evaluate(() => window.testEventSources.at(-1).closed)).toBe(false);
});
