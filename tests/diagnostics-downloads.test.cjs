const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions, FakeElement, fakeDocument } = require("./frontend-harness.cjs");

// downloadRequest of shared.js hands its timeout and the matching German timeout message to the client.
function transport() {
  const calls = [];
  const state = { sessionGeneration: 0 };
  let logins = 0;
  const context = extractFunctions("shared.js", ["downloadRequest"], {
    state,
    showLogin() { logins += 1; },
    AppApi: { download: async (path, options, onUnauthorized) => { calls.push({ path, options }); onUnauthorized(); return "blob"; } },
  });
  return { context, calls, state, logins: () => logins };
}

test("a download waits 25 seconds by default and two minutes when asked", async () => {
  const { context, calls } = transport();
  await context.downloadRequest("/api/a", "Fallback A");
  await context.downloadRequest("/api/b", "Fallback B", 130_000);
  assert.deepEqual(calls.map(({ path, options }) => [path, options.timeoutMs, options.fallback]), [["/api/a", 25_000, "Fallback A"], ["/api/b", 130_000, "Fallback B"]]);
  assert.equal(calls[0].options.timeoutMessage, "Der Server antwortet nicht innerhalb von 25 Sekunden.");
  assert.equal(calls[1].options.timeoutMessage, "Der Download konnte nicht innerhalb von zwei Minuten bestätigt werden.");
});

test("a 401 during a download shows the login only for the session that asked", async () => {
  const { context, state, logins } = transport();
  await context.downloadRequest("/api/a", "Fallback");
  assert.equal(logins(), 1);
  const stale = extractFunctions("shared.js", ["downloadRequest"], {
    state,
    showLogin() { throw new Error("a newer session must not be logged out"); },
    AppApi: { download: async (_path, _options, onUnauthorized) => { state.sessionGeneration += 1; onUnauthorized(); } },
  });
  await stale.downloadRequest("/api/a", "Fallback");
});

// The log and diagnostics buttons download through that request with the long timeout.
function downloadButtons() {
  const requested = [];
  const toasts = [];
  const links = [];
  const document = fakeDocument();
  document.body = new FakeElement();
  document.createElement = (tag) => {
    const link = Object.assign(new FakeElement(tag), { click() { this.clicked = true; }, remove() {} });
    links.push(link);
    return link;
  };
  const context = extractFunctions("diagnostics.js", ["downloadServerLogs", "downloadDiagnostics"], {
    document,
    $: (selector) => document.querySelector(selector),
    downloadRequest: async (...args) => { requested.push(args); return new Blob(["x"]); },
    URL: { createObjectURL: () => "blob:fixture", revokeObjectURL() {} },
    setTimeout() {},
    toast: (message, isError) => toasts.push([message, Boolean(isError)]),
    todayIso: () => "2026-11-11",
    renderConnectivityStatus() {},
  });
  return { context, requested, toasts, links, document };
}

test("the server logs download with the long timeout under the Pacecraft file name", async () => {
  const { context, requested, toasts, links, document } = downloadButtons();
  await context.downloadServerLogs();
  assert.deepEqual(requested[0][0], "/api/logs/download");
  assert.equal(requested[0][2], 130_000);
  assert.equal(links[0].download, "pacecraft-server-logs-2026-11-11.jsonl");
  assert.equal(links[0].clicked, true);
  assert.deepEqual(toasts, [["Server-Logs heruntergeladen", false]]);
  assert.equal(document.querySelector("#logsDownloadButton").disabled, false);
});

test("the diagnostics download with the long timeout and restore their button", async () => {
  const { context, requested, toasts, document } = downloadButtons();
  await context.downloadDiagnostics();
  assert.deepEqual([requested[0][0], requested[0][2]], ["/api/diagnostics", 130_000]);
  assert.deepEqual(toasts, [["Diagnose heruntergeladen", false]]);
  const button = document.querySelector("#diagnosticsButton");
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, "Diagnose herunterladen");
});

test("a failed log download reports the error and re-enables the button", async () => {
  const { context, toasts, document } = downloadButtons();
  context.downloadRequest = async () => { throw new Error("Der Server antwortet nicht."); };
  await context.downloadServerLogs();
  assert.deepEqual(toasts, [["Der Server antwortet nicht.", true]]);
  assert.equal(document.querySelector("#logsDownloadButton").disabled, false);
});

// The backup and the privacy export keep their file URL alive for a second after the click.
function settingsDownloads() {
  const events = [];
  const timers = [];
  const document = fakeDocument();
  document.createElement = (tag) => Object.assign(new FakeElement(tag), { click() { events.push(["click", this.download]); } });
  const context = extractFunctions("settings.js", ["privacyInFlight", "downloadDatabaseBackup", "downloadPrivacyExport"], {
    document,
    $: (selector) => document.querySelector(selector),
    downloadRequest: async () => new Blob(["x"]),
    URL: { createObjectURL: () => "blob:fixture", revokeObjectURL: (url) => events.push(["revoke", url]) },
    setTimeout: (handler, delay) => timers.push({ handler, delay }),
    toast() {},
    setPrivacyButtonBusy() {},
    todayIso: () => "2026-11-11",
  });
  return { context, events, timers };
}

test("the backup and the export revoke their file URL one second after the click", async () => {
  for (const [action, file] of [["downloadDatabaseBackup", "pacecraft-database-2026-11-11.backup"], ["downloadPrivacyExport", "pacecraft-export-2026-11-11.zip"]]) {
    const { context, events, timers } = settingsDownloads();
    await context[action]();
    assert.deepEqual(events, [["click", file]], action);
    assert.deepEqual(timers.map((timer) => timer.delay), [1000]);
    timers[0].handler();
    assert.deepEqual(events.at(-1), ["revoke", "blob:fixture"]);
  }
});
