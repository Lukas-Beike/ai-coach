const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

const RETRY_DELAY_MS = 30000;

function loadNotifier(showNotification, clock) {
  return extractFunctions("notifications.js", ["NOTIFICATION_MAX_ATTEMPTS", "NOTIFICATION_RETRY_DELAY_MS", "reserveNotificationAttempt", "showPwaNotification"], {
    state: { notificationKeys: new Set() },
    notificationPermission: () => "granted",
    navigator: { serviceWorker: { ready: Promise.resolve({ showNotification }) } },
    Date: { now: () => clock.now },
  });
}

test("a persistently rejecting notification is retried at most three times", async () => {
  const clock = { now: 0 };
  let calls = 0;
  const context = loadNotifier(async () => {
    calls += 1;
    throw new Error("Synthetic platform failure");
  }, clock);
  for (let render = 0; render < 10; render += 1) {
    clock.now += RETRY_DELAY_MS;
    await context.showPwaNotification("Titel", { body: "Text" }, "error:synthetic");
  }
  assert.equal(calls, 3);
  assert.equal(context.state.notificationKeys.has("error:synthetic"), true);
});

test("renders inside the retry delay do not resend a rejected notification", async () => {
  const clock = { now: RETRY_DELAY_MS };
  let calls = 0;
  const context = loadNotifier(async () => {
    calls += 1;
    throw new Error("Synthetic platform failure");
  }, clock);
  for (let render = 0; render < 5; render += 1) {
    await context.showPwaNotification("Titel", { body: "Text" }, "error:synthetic");
  }
  assert.equal(calls, 1);
});

test("a successful notification is marked delivered and is not sent again", async () => {
  const clock = { now: 0 };
  let calls = 0;
  const context = loadNotifier(async () => { calls += 1; }, clock);
  await context.showPwaNotification("Titel", { body: "Text" }, "competition:1:2026-10-12");
  clock.now += RETRY_DELAY_MS * 2;
  await context.showPwaNotification("Titel", { body: "Text" }, "competition:1:2026-10-12");
  assert.equal(calls, 1);
  assert.equal(context.state.notificationKeys.has("competition:1:2026-10-12"), true);
});

test("a transient failure followed by success is delivered once", async () => {
  const clock = { now: 0 };
  let calls = 0;
  const context = loadNotifier(async () => {
    calls += 1;
    if (calls === 1) throw new Error("Synthetic transient failure");
  }, clock);
  await context.showPwaNotification("Titel", { body: "Text" }, "error:transient");
  assert.equal(context.state.notificationKeys.has("error:transient"), false);
  clock.now += RETRY_DELAY_MS;
  await context.showPwaNotification("Titel", { body: "Text" }, "error:transient");
  clock.now += RETRY_DELAY_MS;
  await context.showPwaNotification("Titel", { body: "Text" }, "error:transient");
  assert.equal(calls, 2);
  assert.equal(context.state.notificationKeys.has("error:transient"), true);
});
