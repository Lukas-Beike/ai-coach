const { test, expect } = require("@playwright/test");
const { stubSyncJobs } = require("./helpers/sync-jobs");

test("@responsive the week button removes old Garmin and Wahoo entries although no unit waits for a sync", async ({ page, request }) => {
  test.setTimeout(180_000);
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  const posted = await stubSyncJobs(page);
  const garminOld = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa";
  const wahooOld = "bbbbbbbb-1111-4111-8111-bbbbbbbbbbbb";
  const cleanup = {
    garmin: [{ id: garminOld, name: "Kraft A", date: "2026-11-05" }],
    wahoo: [{ id: wahooOld, name: "Gelöschter Wahoo-Plan", date: "" }],
  };
  let carrier = "";
  // Every unit is synced; the nearest future one carries the leftovers, as the server projects it.
  const mark = (node) => {
    if (Array.isArray(node)) node.forEach(mark);
    else if (node && typeof node === "object") {
      if (node.local_id && node.push_pending) {
        node.push_pending = { intervals: false };
        if (node.local_id === carrier) node.push_cleanup = cleanup;
      }
      Object.values(node).forEach(mark);
    }
  };
  await page.route(/\/api\/(bootstrap|plan)(\?|$)/, async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    if (!carrier) {
      const today = new Date().toISOString().slice(0, 10);
      carrier = (body.planned || []).filter((unit) => unit.local_id && unit.push_pending && String(unit.date || "") > today).map((unit) => unit.local_id)[0] || "";
    }
    mark(body);
    body.garmin = { ...(body.garmin || {}), configured: true };
    body.wahoo = { ...(body.wahoo || {}), connected: true };
    await route.fulfill({ status: response.status(), contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/#plan/overview");
  await page.waitForFunction(() => state.initialStateLoaded);
  expect(carrier).not.toBe("");
  // Both leftovers (one dated before this week, one undated) belong to the current week's button.
  const button = page.locator(".planned-week").filter({ has: page.locator(".planned-day.is-today") }).locator(".planned-week-sync-button");
  await button.evaluate((element) => {
    for (let node = element.parentElement; node; node = node.parentElement) if (node.tagName === "DETAILS") node.open = true;
  });
  await button.scrollIntoViewIfNeeded();
  await expect(button).toBeVisible();
  await expect(page.locator(".planned-week-sync-button")).toHaveCount(1);
  expect((await button.boundingBox()).height).toBeGreaterThanOrEqual(28);
  // Nothing is sent before the athlete asks for it.
  expect(posted).toHaveLength(0);
  await button.click();
  await expect.poll(() => posted.length).toBe(2);
  expect(posted[0]).toEqual({ provider: "garmin", type: "plan_push", payload: { entries: [{ library_workout_id: garminOld, remove: true }] } });
  expect(posted[1]).toEqual({ provider: "wahoo", type: "plan_push", payload: { entries: [{ library_workout_id: wahooOld, remove: true }] } });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  await page.unrouteAll({ behavior: "ignoreErrors" });
});
