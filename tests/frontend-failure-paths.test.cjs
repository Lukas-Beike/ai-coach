const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

// Line endings are normalized so the column-0 function boundaries match on any checkout.
const readPublic = (file) => fs.readFileSync(path.join(__dirname, "../public", file), "utf8").replace(/\r\n/g, "\n");
const authSource = readPublic("auth.js");
const settingsSource = readPublic("settings.js");
const coachSource = readPublic("coach.js");

// Extracts one top-level function, from its declaration through the closing brace at column 0.
function extractFunction(source, name) {
  const match = new RegExp(`^(?:async )?function ${name}\\(`, "m").exec(source);
  assert.ok(match, `${name} must exist`);
  const start = match.index;
  const end = source.indexOf("\n}\n", start);
  assert.ok(end > start, `${name} must end at a column-0 brace`);
  return source.slice(start, end + 3);
}

function abortError() {
  return Object.assign(new Error("Session ended"), { name: "AbortError" });
}

function httpError(status, message = "Fehler") {
  return Object.assign(new Error(message), { status, reason: "http_error" });
}

// ---- F3: logout keeps the app open unless the server confirmed the logout ----

function logoutHarness(api) {
  const counts = { showLogin: 0 };
  const toasts = [];
  const context = vm.createContext({
    confirmDiscardChanges: async () => true,
    requestConfirmation: async () => true,
    api,
    showLogin() { counts.showLogin += 1; },
    toast(message, error = false) { toasts.push({ message, error }); },
  });
  vm.runInContext(extractFunction(authSource, "logout"), context);
  return { context, counts, toasts };
}

test("logout shows the login screen after the server confirmed the logout", async () => {
  const calls = [];
  const { context, counts, toasts } = logoutHarness(async (path) => { calls.push(path); return {}; });
  await context.logout();
  assert.deepEqual(calls, ["/api/logout"]);
  assert.equal(counts.showLogin, 1);
  assert.deepEqual(toasts, []);
});

test("the login screen clears the device snapshot, view and message caches", () => {
  // showLogin runs after logout, a 401 and an unauthenticated start; the caches
  // hold athlete data and are removed by clearStateSnapshot (state-loader tests).
  assert.match(extractFunction(authSource, "showLogin"), /^\s*clearStateSnapshot\(\);$/m);
});

test("a failed logout request keeps the app open, reports the error and allows a retry", async () => {
  const { context, counts, toasts } = logoutHarness(async () => { throw httpError(500, "Serverfehler"); });
  await context.logout();
  assert.equal(counts.showLogin, 0);
  assert.deepEqual(toasts, [{ message: "Abmelden fehlgeschlagen. Bitte erneut versuchen.", error: true }]);
});

test("a network failure during logout does not show the login screen", async () => {
  const { context, counts, toasts } = logoutHarness(async () => { throw Object.assign(new Error("offline"), { status: 0 }); });
  await context.logout();
  assert.equal(counts.showLogin, 0);
  assert.equal(toasts.length, 1);
  assert.equal(toasts[0].error, true);
});

test("logout after a 401 or an ended session stays silent because api() already showed the login", async () => {
  for (const failure of [httpError(401, "Deine Sitzung ist abgelaufen."), abortError()]) {
    const { context, counts, toasts } = logoutHarness(async () => { throw failure; });
    await context.logout();
    assert.equal(counts.showLogin, 0);
    assert.deepEqual(toasts, []);
  }
});

// ---- F6: a failed cancel leaves the stream running and the cancel retryable ----

function cancelHarness() {
  const controller = new AbortController();
  const state = {
    busy: true,
    chatServerOperationId: null,
    chatStream: { controller, operationId: "op-1", cancelRequested: false },
    chatRequest: { phase: "running", cancelRequested: false, operationId: "op-1" },
  };
  const button = { hidden: false, disabled: false, attributes: {}, title: "", setAttribute(name, value) { this.attributes[name] = value; } };
  const counts = { polls: 0, controls: 0 };
  const toasts = [];
  const apiCalls = [];
  let settle = null;
  const context = vm.createContext({
    state,
    counts,
    toasts,
    controlCalls: [],
    api: (path, options) => {
      apiCalls.push({ path, body: JSON.parse(options.body) });
      return new Promise((resolve, reject) => { settle = { resolve, reject }; });
    },
    $: () => button,
    scheduleChatStatusPoll() { counts.polls += 1; },
    toast(message, error = false) { toasts.push({ message, error }); },
  });
  // updateChatControls is reduced to the cancel button, which is the part under test.
  vm.runInContext([
    "let chatCancelInFlight = false;",
    extractFunction(coachSource, "restoreChatCancelAfterFailure"),
    extractFunction(coachSource, "cancelChat"),
    extractFunction(coachSource, "updateChatCancelButton"),
    "function updateChatControls() { controlCalls.push(1); updateChatCancelButton($('#cancelChatButton'), { reconciling: false }); }",
  ].join("\n"), context);
  return { context, controller, state, button, counts, toasts, apiCalls, settle: () => settle };
}

test("cancelling marks the request as stopping and aborts the stream after the server accepts it", async () => {
  const harness = cancelHarness();
  const pending = harness.context.cancelChat();
  assert.equal(harness.state.chatRequest.cancelRequested, true);
  assert.equal(harness.state.chatRequest.phase, "recovering");
  harness.settle().resolve({});
  await pending;
  assert.deepEqual(harness.apiCalls, [{ path: "/api/chat/cancel", body: { operation_id: "op-1" } }]);
  assert.equal(harness.controller.signal.aborted, true);
  assert.equal(harness.counts.polls, 1);
  assert.deepEqual(harness.toasts, []);
});

test("a failed cancel keeps the stream running and restores a retryable stop button", async () => {
  const harness = cancelHarness();
  const pending = harness.context.cancelChat();
  harness.settle().reject(httpError(500, "Serverfehler"));
  await pending;
  assert.equal(harness.controller.signal.aborted, false);
  assert.equal(harness.state.chatStream.cancelRequested, false);
  assert.equal(harness.state.chatRequest.cancelRequested, false);
  assert.equal(harness.state.chatRequest.phase, "running");
  assert.equal(harness.counts.polls, 0);
  assert.deepEqual(harness.toasts, [{ message: "Stoppen fehlgeschlagen. Bitte erneut versuchen.", error: true }]);
  assert.equal(harness.button.disabled, false);
  assert.equal(harness.button.attributes["aria-label"], "Antwort stoppen");
  assert.ok(harness.context.controlCalls.length >= 1);
});

test("a failed cancel keeps a phase that the stream reached while the request was pending", async () => {
  const harness = cancelHarness();
  const pending = harness.context.cancelChat();
  harness.state.chatRequest.phase = "reconciling";
  harness.settle().reject(httpError(500, "Serverfehler"));
  await pending;
  assert.equal(harness.state.chatRequest.phase, "reconciling");
  assert.equal(harness.state.chatRequest.cancelRequested, false);
});

test("a second stop click while the cancel is pending sends nothing and the retry stays possible", async () => {
  const harness = cancelHarness();
  const pending = harness.context.cancelChat();
  assert.equal(harness.button.disabled, true);
  await harness.context.cancelChat();
  assert.equal(harness.apiCalls.length, 1);
  harness.settle().reject(httpError(500, "Serverfehler"));
  await pending;
  assert.equal(harness.state.chatStream.cancelRequested, false);
  assert.equal(harness.state.chatRequest.cancelRequested, false);
  assert.equal(harness.button.disabled, false);
  const retry = harness.context.cancelChat();
  assert.equal(harness.apiCalls.length, 2);
  harness.settle().resolve({});
  await retry;
  assert.equal(harness.controller.signal.aborted, true);
});

test("a deferred cancel that fails once the operation id arrived becomes retryable", async () => {
  const harness = cancelHarness();
  // The stop click came before the operation id; the stream then retries the cancel.
  harness.state.chatStream.cancelRequested = true;
  harness.state.chatRequest.cancelRequested = true;
  const pending = harness.context.cancelChat();
  harness.settle().reject(httpError(500, "Serverfehler"));
  await pending;
  assert.equal(harness.state.chatStream.cancelRequested, false);
  assert.equal(harness.state.chatRequest.cancelRequested, false);
  assert.equal(harness.button.disabled, false);
});

test("a cancel that fails after the session ended restores the flags without a stale error toast", async () => {
  const harness = cancelHarness();
  const pending = harness.context.cancelChat();
  harness.settle().reject(abortError());
  await pending;
  assert.equal(harness.controller.signal.aborted, false);
  assert.equal(harness.state.chatRequest.cancelRequested, false);
  assert.deepEqual(harness.toasts, []);
});
