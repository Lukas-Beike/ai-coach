const { test, expect } = require("@playwright/test");
const { stubSyncJobs } = require("./helpers/sync-jobs");

test("@responsive a pending planned unit offers a sync button that queues its push", async ({ page, request }) => {
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
  const button = page.locator(".planned-entry .planned-sync-button").first();
  await button.evaluate((element) => {
    for (let node = element.parentElement; node; node = node.parentElement) if (node.tagName === "DETAILS" && !node.classList.contains("planned-entry")) node.open = true;
  });
  await button.scrollIntoViewIfNeeded();
  await expect(button).toBeVisible();
  await expect(button).toHaveText("Synchronisieren");
  const card = button.locator("xpath=ancestor::details[contains(@class,'planned-entry')]");
  await button.click();
  await expect.poll(() => posted.length).toBeGreaterThan(0);
  // The click queues the push and leaves the card closed.
  expect(await card.evaluate((element) => element.open)).toBe(false);
  for (const body of posted) {
    expect(body.type).toBe("plan_push");
    expect(body.payload.entries).toHaveLength(1);
    expect(body.payload.entries[0].expected_payload_hash).toMatch(/^[0-9a-f]{64}$/);
  }
  const hit = await button.boundingBox();
  expect(hit.height).toBeGreaterThanOrEqual(32);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  // Background polls may still be routed; stop them before the page closes.
  await page.unrouteAll({ behavior: "ignoreErrors" });
});
