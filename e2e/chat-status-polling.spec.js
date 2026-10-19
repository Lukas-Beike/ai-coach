const { test, expect } = require("@playwright/test");

// Coach status polling is timer-driven. The clock is installed before navigation so the app's
// own timers run on Playwright's clock, and quiet observation windows are advanced with
// runFor() instead of waiting on wall-clock time.

function isStatusPoll(request) {
  return new URL(request.url()).pathname === "/api/chat/status";
}

function recordStatusPolls(page) {
  const polls = [];
  page.on("request", (request) => {
    if (isStatusPoll(request)) polls.push(request.url());
  });
  return polls;
}

function recordFinishedStatusPolls(page) {
  const finished = [];
  const record = (request) => {
    if (isStatusPoll(request)) finished.push(request.url());
  };
  page.on("requestfinished", record);
  page.on("requestfailed", record);
  return finished;
}

// Request events reach the Node side asynchronously. A round trip to the page after the clock
// fired its timers gives those events a chance to arrive before counts are compared.
async function advanceQuietWindow(page, ms) {
  await page.clock.runFor(ms);
  await page.evaluate(() => undefined);
}

// The default poll cadence is 1.5s, so one window of that length lets any poll already
// scheduled by a previous step fire and finish before a baseline is taken.
async function settleStatusPolls(page) {
  await advanceQuietWindow(page, 1_500);
}

const CHAT_FORM = "#chatForm";

test("idle Coach status is not polled after bootstrap while another tab is open @responsive", async ({ page }) => {
  await page.clock.install();
  const statusPolls = recordStatusPolls(page);
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => statusPolls.length).toBeGreaterThanOrEqual(1);
  await settleStatusPolls(page);
  await page.getByRole("link", { name: "Kalender", exact: true }).click();
  await expect(page.locator("#workoutsPanel")).toBeVisible();
  await settleStatusPolls(page);
  const baseline = statusPolls.length;
  await advanceQuietWindow(page, 6_000);
  expect(statusPolls.length - baseline, "status polls while idle").toBe(0);
});

test("reloading during a running Coach job without the event stream polls until the job finishes, then stops @responsive", async ({ page }) => {
  await page.clock.install();
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
  // The busy state is the observable form control state, not the app's internal busy flag.
  await expect(page.locator(CHAT_FORM)).toHaveClass(/is-busy/);
  await expect.poll(() => runningResponses).toBe(3);
  await expect(page.locator(CHAT_FORM)).not.toHaveClass(/is-busy/);
  await settleStatusPolls(page);
  const baseline = statusPolls.length;
  await advanceQuietWindow(page, 6_000);
  expect(statusPolls.length - baseline, "status polls after the job finished").toBe(0);
});

test("with the event stream connected, a running Coach job is checked again when its answer arrives @responsive", async ({ page }) => {
  await page.clock.install();
  const statusPolls = recordStatusPolls(page);
  const finishedPolls = recordFinishedStatusPolls(page);
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
  for (let window = 0; window < 5; window += 1) {
    const before = statusPolls.length;
    await advanceQuietWindow(page, 2_000);
    await expect.poll(() => statusPolls.length - finishedPolls.length).toBe(0);
    if (statusPolls.length === before) break;
  }
  const baseline = statusPolls.length;
  // A healthy stream replaces the frequent status polls with a slow safety check.
  await advanceQuietWindow(page, 5_000);
  expect(statusPolls.length - baseline, "status polls while the stream is connected").toBe(0);
  answered = true;
  // Stimulus equivalent to an SSE "coach" message from the server; the stream itself is not controllable from the test.
  await page.evaluate(() => handleStateEvent({ type: "coach", lastEventId: "", data: JSON.stringify({ role: "assistant", message_id: 2 }) }));
  await expect(page.locator(CHAT_FORM)).not.toHaveClass(/is-busy/);
  expect(statusPolls.length - baseline, "the answer event checks the status once").toBe(1);
});

test("a Coach turn submitted elsewhere triggers one status check while idle @responsive", async ({ page }) => {
  await page.clock.install();
  const statusPolls = recordStatusPolls(page);
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => statusPolls.length).toBeGreaterThanOrEqual(1);
  await settleStatusPolls(page);
  const baseline = statusPolls.length;
  await page.evaluate(() => handleStateEvent({ type: "coach", lastEventId: "", data: JSON.stringify({ role: "user", message_id: 1 }) }));
  await expect.poll(() => statusPolls.length - baseline).toBe(1);
  await settleStatusPolls(page);
  await advanceQuietWindow(page, 6_000);
  expect(statusPolls.length - baseline, "only the event-triggered status check").toBe(1);
});
