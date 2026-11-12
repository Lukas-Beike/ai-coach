const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions, fakeDocument } = require("./frontend-harness.cjs");

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

test("a competition notification names the day without the competition's name", () => {
  const { competitionCountdownText } = extractFunctions("notifications.js", ["competitionCountdownText"]);
  assert.equal(competitionCountdownText(0), "Der Wettkampf ist heute.");
  assert.equal(competitionCountdownText(1), "Der Wettkampf ist morgen.");
  assert.equal(competitionCountdownText(3), "Der Wettkampf ist in 3 Tagen.");
});

test("notifications stay opt-in: the status names the permission and an unsupported browser disables the button", () => {
  const document = fakeDocument();
  const context = extractFunctions("notifications.js", ["notificationPermission", "renderNotificationStatus"], {
    $: (selector) => document.querySelector(selector),
    Notification: { permission: "default" },
  });
  const status = document.querySelector("#notificationStatus");
  const button = document.querySelector("#notificationEnableButton");
  const shown = [];
  for (const permission of ["default", "granted", "denied"]) {
    context.Notification.permission = permission;
    context.renderNotificationStatus();
    shown.push([status.textContent, button.hidden, button.disabled]);
  }
  assert.deepEqual(shown, [["Noch nicht aktiviert", false, false], ["Aktiv", true, false], ["Im Browser blockiert", false, false]]);
  const unsupported = extractFunctions("notifications.js", ["notificationPermission", "renderNotificationStatus"], { $: (selector) => document.querySelector(selector) });
  unsupported.renderNotificationStatus();
  assert.deepEqual([status.textContent, button.disabled], ["Von diesem Browser nicht unterstützt", true]);
});
