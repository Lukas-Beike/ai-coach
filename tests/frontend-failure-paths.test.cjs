const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions, FakeElement, fakeDocument } = require("./frontend-harness.cjs");

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
  const context = extractFunctions("auth.js", ["logout"], {
    confirmDiscardChanges: async () => true,
    requestConfirmation: async () => true,
    api,
    showLogin() { counts.showLogin += 1; },
    toast(message, error = false) { toasts.push({ message, error }); },
  });
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
  assert.match(extractFunctions("auth.js", ["showLogin"]).showLogin.toString(), /^\s*clearStateSnapshot\(\);$/m);
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
  // updateChatControls is reduced to the cancel button, which is the part under test.
  const context = extractFunctions("coach.js", ["chatCancelInFlight", "restoreChatCancelAfterFailure", "cancelChat", "updateChatCancelButton"], {
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
    updateChatControls() { context.controlCalls.push(1); context.updateChatCancelButton(button, { reconciling: false }); },
  });
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

test("the session-ended abort is German, marked, and never toasted", () => {
  const rendered = [];
  const node = { replaceChildren(...args) { rendered.push(args); }, querySelector: () => null, append() {}, setAttribute() {} };
  const context = extractFunctions("shared.js", ["SESSION_ENDED_MESSAGE", "sessionEndedError", "isSessionEndedError", "toast"], {
    DOMException,
    $: () => node,
    document: fakeDocument(),
    clearTimeout() {},
    setTimeout() {},
    hideToast() {},
  });
  const error = context.sessionEndedError();
  assert.equal(error.name, "AbortError");
  assert.equal(context.isSessionEndedError(error), true);
  assert.equal(context.isSessionEndedError(abortError()), false);
  assert.doesNotMatch(error.message, /Session ended/);
  context.toast(error.message, true);
  assert.deepEqual(rendered, []);
});

// ---- toasts: an error stays long enough to read and can be dismissed ----

function toastHarness() {
  const document = fakeDocument();
  const node = document.querySelector("#toast");
  node.querySelector = (selector) => node.children.find((child) => child.className === selector.slice(1)) || null;
  const timers = [];
  const context = extractFunctions("shared.js", ["SESSION_ENDED_MESSAGE", "hideToast", "toast"], {
    document,
    $: (selector) => document.querySelector(selector),
    setTimeout: (handler, delay) => { timers.push({ handler, delay }); return timers.length; },
    clearTimeout() {},
  });
  return { context, node, timers };
}

test("an error toast is an assertive alert with a labelled close button and lasts eight seconds", () => {
  const { context, node, timers } = toastHarness();
  context.toast("Speichern fehlgeschlagen", true);
  assert.equal(node.className, "toast show error");
  assert.deepEqual([node.attributes.role, node.attributes["aria-live"]], ["alert", "assertive"]);
  const close = node.children.find((child) => child.className === "toast-close");
  assert.equal(close.attributes["aria-label"], "Meldung schließen");
  assert.equal(timers.at(-1).delay, 8000);
  close.fire("click");
  assert.equal(node.className, "toast");
  assert.equal(close.inert, true);
});

test("a normal toast is a polite status without a close button and lasts three seconds", () => {
  const { context, node, timers } = toastHarness();
  context.toast("Gespeichert");
  assert.equal(node.className, "toast show");
  assert.deepEqual([node.attributes.role, node.attributes["aria-live"]], ["status", "polite"]);
  assert.equal(node.children.length, 1);
  assert.equal(timers.at(-1).delay, 3000);
});

// ---- scroll regions: keyboard users can reach a table that scrolls sideways ----

test("a horizontally scrolling table region is focusable and named", () => {
  const { makeScrollRegionFocusable } = extractFunctions("shared.js", ["makeScrollRegionFocusable"]);
  const region = new FakeElement("div");
  assert.equal(makeScrollRegionFocusable(region, "Runden dieser Einheit"), region);
  assert.equal(region.tabIndex, 0);
  assert.deepEqual([region.attributes.role, region.attributes["aria-label"]], ["region", "Runden dieser Einheit"]);
});
