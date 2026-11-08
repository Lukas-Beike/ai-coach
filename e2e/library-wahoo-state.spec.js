const { test, expect } = require("@playwright/test");

const HASH = "a".repeat(64);

test("@responsive a changed Wahoo library workout offers the explicit send", async ({ page, request }) => {
  test.setTimeout(180_000);
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  const posted = [];
  // The fixture never contacts a provider: answer the job queue and its poll here.
  await page.route("**/api/sync/jobs", async (route) => {
    posted.push(JSON.parse(route.request().postData() || "{}"));
    await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ id: `job-${posted.length}`, status: "queued" }) });
  });
  await page.route("**/api/sync/jobs/job-*", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ id: "job", status: "completed", items: [] }) }));
  // The fixture has no Wahoo link; mark the first template changed and the second synced.
  await page.route("**/api/library*", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.workouts = (body.workouts || []).map((workout, index) => (index < 2 ? { ...workout, wahoo_state: { state: index === 0 ? "changed" : "synced", payload_hash: HASH } } : workout));
    await route.fulfill({ status: response.status(), contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/#plan/library");
  await page.waitForFunction(() => state.initialStateLoaded);
  await page.locator("#library details.library-sport").evaluateAll((sections) => sections.forEach((section) => { section.open = true; }));
  const changed = page.locator(".library-wahoo-state.is-changed");
  const synced = page.locator(".library-wahoo-state.is-synced");
  await expect(changed).toHaveText("Wahoo: geändert");
  await expect(synced).toHaveText("Wahoo: synchron");
  // Only a changed workout offers the send, and nothing is sent unprompted.
  await expect(page.locator(".library-wahoo-send")).toHaveCount(1);
  expect(posted).toHaveLength(0);
  const button = page.locator(".library-wahoo-send");
  await button.scrollIntoViewIfNeeded();
  expect((await button.boundingBox()).height).toBeGreaterThanOrEqual(44);
  await button.click();
  await expect.poll(() => posted.length).toBe(1);
  expect(posted[0].provider).toBe("wahoo");
  expect(posted[0].type).toBe("plan_push");
  expect(posted[0].payload.entries).toHaveLength(1);
  expect(posted[0].payload.entries[0].expected_payload_hash).toBe(HASH);
  expect(posted[0].payload.entries[0].library_workout_id).toMatch(/^[0-9a-f-]{36}$/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  // Background polls may still be routed; stop them before the page closes.
  await page.unrouteAll({ behavior: "ignoreErrors" });
});
