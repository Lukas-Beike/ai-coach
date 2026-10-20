const { test, expect } = require("@playwright/test");

// Coach status polling is timer-driven. The clock is installed before navigation so the app's
// own timers run on Playwright's clock, and quiet observation windows are advanced with
// runFor() instead of waiting on wall-clock time.

// Status polls are counted in the page when the app calls fetch(). Playwright's request events
// reach the test asynchronously, so a poll fired in one clock window could otherwise be counted
// only after the next baseline was taken. Returns a function that reads the current count.
async function recordStatusPolls(page) {
  await page.addInitScript(() => {
    let count = 0;
    const nativeFetch = globalThis.fetch;
    globalThis.fetch = function countingFetch(input, init) {
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (url.pathname === "/api/chat/status") count += 1;
      return nativeFetch.call(this, input, init);
    };
    globalThis.e2eStatusPollCount = () => count;
  });
  return () => page.evaluate(() => globalThis.e2eStatusPollCount());
}

async function advanceQuietWindow(page, ms) {
  await page.clock.runFor(ms);
}

// The default poll cadence is 1.5s, so one window of that length lets any poll already
// scheduled by a previous step fire and finish before a baseline is taken.
async function settleStatusPolls(page) {
  await advanceQuietWindow(page, 1_500);
}

const CHAT_FORM = "#chatForm";

test("idle Coach status is not polled after bootstrap while another tab is open @responsive", async ({ page }) => {
  await page.clock.install();
  const statusPolls = await recordStatusPolls(page);
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(statusPolls).toBeGreaterThanOrEqual(1);
  await settleStatusPolls(page);
  await page.getByRole("link", { name: "Kalender", exact: true }).click();
  await expect(page.locator("#workoutsPanel")).toBeVisible();
  await settleStatusPolls(page);
  const baseline = await statusPolls();
  await advanceQuietWindow(page, 6_000);
  expect(await statusPolls() - baseline, "status polls while idle").toBe(0);
});

test("reloading during a running Coach job without the event stream polls until the job finishes, then stops @responsive", async ({ page }) => {
  await page.clock.install();
  const statusPolls = await recordStatusPolls(page);
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
  // The busy state is the observable form control state, not the app's internal busy flag.
  await expect(page.locator(CHAT_FORM)).toHaveClass(/is-busy/);
  await expect.poll(() => runningResponses).toBe(3);
  await expect(page.locator(CHAT_FORM)).not.toHaveClass(/is-busy/);
  await settleStatusPolls(page);
  const baseline = await statusPolls();
  await advanceQuietWindow(page, 6_000);
  expect(await statusPolls() - baseline, "status polls after the job finished").toBe(0);
});

test("with the event stream connected, a running Coach job is checked again when its answer arrives @responsive", async ({ page }) => {
  await page.clock.install();
  const statusPolls = await recordStatusPolls(page);
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
  await expect(page.locator(CHAT_FORM)).toHaveClass(/is-busy/);
  // Justified internal probe: the SSE "ready" frame is neither a DOM change nor a distinct network
  // response, so the test waits for the client's own stream-health flag before measuring. Every
  // assertion below observes requests and control state only.
  await expect.poll(() => page.evaluate(() => stateEventStreamHealthy())).toBe(true);
  // A fast check queued before the stream was ready may still run, and one that settles later
  // can queue a recheck. Settle until no check is in flight and a fast-cadence window adds none.
  // Justified internal probe: a check has settled once the app handled its response and scheduled
  // the next one, which happens after the request event and is not visible on the network.
  const statusPollSettled = () => page.evaluate(() => state.chatStatusPollInFlight === null);
  await expect.poll(statusPollSettled).toBe(true);
  for (let window = 0; window < 5; window += 1) {
    const before = await statusPolls();
    await advanceQuietWindow(page, 2_000);
    await expect.poll(statusPollSettled).toBe(true);
    if (await statusPolls() === before) break;
  }
  const baseline = await statusPolls();
  // A healthy stream replaces the frequent status polls with a slow safety check.
  await advanceQuietWindow(page, 5_000);
  expect(await statusPolls() - baseline, "status polls while the stream is connected").toBe(0);
  answered = true;
  // Stimulus equivalent to an SSE "coach" message from the server; the stream itself is not controllable from the test.
  await page.evaluate(() => handleStateEvent({ type: "coach", lastEventId: "", data: JSON.stringify({ role: "assistant", message_id: 2 }) }));
  await expect(page.locator(CHAT_FORM)).not.toHaveClass(/is-busy/);
  expect(await statusPolls() - baseline, "the answer event checks the status once").toBe(1);
});

test("a Coach turn submitted elsewhere triggers one status check while idle @responsive", async ({ page }) => {
  await page.clock.install();
  const statusPolls = await recordStatusPolls(page);
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(statusPolls).toBeGreaterThanOrEqual(1);
  await settleStatusPolls(page);
  const baseline = await statusPolls();
  await page.evaluate(() => handleStateEvent({ type: "coach", lastEventId: "", data: JSON.stringify({ role: "user", message_id: 1 }) }));
  await expect.poll(async () => await statusPolls() - baseline).toBe(1);
  await settleStatusPolls(page);
  await advanceQuietWindow(page, 6_000);
  expect(await statusPolls() - baseline, "only the event-triggered status check").toBe(1);
});
