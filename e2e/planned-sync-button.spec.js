const { test, expect } = require("@playwright/test");
const { stubSyncJobs } = require("./helpers/sync-jobs");
const { showCalendarEntry } = require("./helpers/ui");

test("@responsive a week with pending units offers one sync button that queues their pushes", async ({ page, request }) => {
  test.setTimeout(180_000);
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  const posted = await stubSyncJobs(page);
  // The fixture configures no provider; the button only targets configured ones.
  await page.route("**/api/bootstrap*", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.configured = { ...(body.configured || {}), intervals: true };
    await route.fulfill({ status: response.status(), contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/#plan/overview");
  await page.waitForFunction(() => state.initialStateLoaded);
  // Late in the week the next pending unit can sit in the following week.
  await showCalendarEntry(page, { pending: "intervals" });
  const button = page.locator(".planned-week .planned-week-sync-button").first();
  await button.evaluate((element) => {
    for (let node = element.parentElement; node; node = node.parentElement) if (node.tagName === "DETAILS") node.open = true;
  });
  await button.scrollIntoViewIfNeeded();
  await expect(button).toBeVisible();
  await expect(button).toHaveText("Woche synchronisieren");
  // Nothing is sent before the athlete asks for it.
  expect(posted).toHaveLength(0);
  await button.click();
  await expect.poll(() => posted.length).toBeGreaterThan(0);
  for (const body of posted) {
    expect(body.type).toBe("plan_push");
    expect(body.provider).toBe("intervals");
    expect(body.payload.entries.length).toBeGreaterThan(0);
    expect(body.payload.entries.length).toBeLessThanOrEqual(28);
    for (const entry of body.payload.entries) expect(entry.expected_payload_hash).toMatch(/^[0-9a-f]{64}$/);
  }
  const hit = await button.boundingBox();
  expect(hit.height).toBeGreaterThanOrEqual(28);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  // Background polls may still be routed; stop them before the page closes.
  await page.unrouteAll({ behavior: "ignoreErrors" });
});
