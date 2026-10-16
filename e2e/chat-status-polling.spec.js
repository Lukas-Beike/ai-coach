const { test, expect } = require("@playwright/test");

function recordStatusPolls(page) {
  const polls = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/chat/status") polls.push(request.url());
  });
  return polls;
}

async function waitForStatusPollIdle(page) {
  await expect.poll(() => page.evaluate(() => Boolean(state.chatStatusPollInFlight || state.chatStatusTimer))).toBe(false);
}

test("idle Coach status is not polled after bootstrap while another tab is open @responsive", async ({ page }) => {
  const statusPolls = recordStatusPolls(page);
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => statusPolls.length).toBeGreaterThanOrEqual(1);
  await waitForStatusPollIdle(page);
  await page.getByRole("link", { name: "Kalender", exact: true }).click();
  await expect(page.locator("#workoutsPanel")).toBeVisible();
  await waitForStatusPollIdle(page);
  const baseline = statusPolls.length;
  await page.waitForTimeout(6_000);
  expect(statusPolls.length - baseline, "status polls while idle").toBe(0);
});

test("reloading during a running Coach job without the event stream polls until the job finishes, then stops @responsive", async ({ page }) => {
  const statusPolls = recordStatusPolls(page);
  let runningResponses = 0;
  // Without the event stream, status polling is the only way to see the job finish.
  await page.route("**/api/state/events**", (route) => route.abort());
  // Simulate a background Coach job that is still running after reload; the
  // fourth and later responses fall through to the real fixture server (idle).
  await page.route("**/api/chat/status", async (route) => {
    if (runningResponses < 3) {
      runningResponses += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "running", operation_id: "e2e-running-operation", mode: "background" }),
      });
      return;
    }
    await route.fallback();
  });
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => state.busy)).toBe(true);
  await expect.poll(() => runningResponses).toBe(3);
  await expect.poll(() => page.evaluate(() => state.busy)).toBe(false);
  await waitForStatusPollIdle(page);
  const baseline = statusPolls.length;
  await page.waitForTimeout(6_000);
  expect(statusPolls.length - baseline, "status polls after the job finished").toBe(0);
});

test("with the event stream connected, a running Coach job is checked again when its answer arrives @responsive", async ({ page }) => {
  const statusPolls = recordStatusPolls(page);
  let answered = false;
  await page.route("**/api/chat/status", async (route) => {
    if (!answered) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "running", operation_id: "e2e-running-operation", mode: "background" }),
      });
      return;
    }
    await route.fallback();
  });
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => state.busy)).toBe(true);
  await expect.poll(() => page.evaluate(() => stateEventStreamHealthy())).toBe(true);
  // A fast check queued before the stream was ready may still run once.
  await page.waitForTimeout(2_000);
  const baseline = statusPolls.length;
  // A healthy stream replaces the frequent status polls with a slow safety check.
  await page.waitForTimeout(5_000);
  expect(statusPolls.length - baseline, "status polls while the stream is connected").toBe(0);
  answered = true;
  await page.evaluate(() => handleStateEvent({ type: "coach", lastEventId: "", data: JSON.stringify({ role: "assistant", message_id: 2 }) }));
  await expect.poll(() => page.evaluate(() => state.busy)).toBe(false);
  expect(statusPolls.length - baseline, "the answer event checks the status once").toBe(1);
});

test("a Coach turn submitted elsewhere triggers one status check while idle @responsive", async ({ page }) => {
  const statusPolls = recordStatusPolls(page);
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => statusPolls.length).toBeGreaterThanOrEqual(1);
  await waitForStatusPollIdle(page);
  const baseline = statusPolls.length;
  await page.evaluate(() => handleStateEvent({ type: "coach", lastEventId: "", data: JSON.stringify({ role: "user", message_id: 1 }) }));
  await expect.poll(() => statusPolls.length - baseline).toBe(1);
  await waitForStatusPollIdle(page);
  await page.waitForTimeout(6_000);
  expect(statusPolls.length - baseline, "only the event-triggered status check").toBe(1);
});
