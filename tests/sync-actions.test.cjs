const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const publicDir = path.join(__dirname, "../public");
const statusSource = fs.readFileSync(path.join(publicDir, "sync-status.js"), "utf8");
const actionsSource = fs.readFileSync(path.join(publicDir, "sync-actions.js"), "utf8");

// Runs the real waitForSyncJob against one terminal job DTO; non-retryable errors
// throw before any polling delay, so the test does not wait.
function waitForJob(job) {
  const start = statusSource.indexOf("const NON_RETRYABLE_PROVIDER_ERRORS");
  const end = statusSource.indexOf("function providerRequiresManualAttention");
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({ api: async () => job });
  vm.runInContext(statusSource.slice(start, end), context);
  vm.runInContext(actionsSource, context);
  return vm.runInContext("waitForSyncJob('job-1')", context);
}

const FALLBACK = "Die Anbindung ist nicht vollständig konfiguriert. Bitte die Verbindungseinstellungen unter Mehr prüfen.";

test("an expired Garmin login shows the item's actionable detail, not the configuration fallback", async () => {
  await assert.rejects(waitForJob({
    id: "job-1", status: "failed", error_class: "auth_required", items: [
      { status: "failed", error_class: "auth_required", error_detail: "Garmin-Login abgelaufen. Bitte MFA-Code eingeben." },
    ],
  }), { message: "Garmin-Login abgelaufen. Bitte MFA-Code eingeben." });
});

test("a non-retryable item takes precedence over another failed item", async () => {
  await assert.rejects(waitForJob({
    id: "job-1", status: "failed", error_class: "invalid_configuration", items: [
      { status: "failed", error_class: "plan_push_error", error_detail: "Generic push failure." },
      { status: "failed", error_class: "invalid_configuration", error_detail: "Der API-Schlüssel fehlt." },
    ],
  }), { message: "Der API-Schlüssel fehlt." });
});

test("a top-level job detail is used when no item explains the failure", async () => {
  await assert.rejects(waitForJob({
    id: "job-1", status: "failed", error_class: "invalid_configuration", error_detail: "Top-level detail.", items: [],
  }), { message: "Top-level detail." });
});

test("without any detail the configuration fallback is still shown", async () => {
  await assert.rejects(waitForJob({
    id: "job-1", status: "failed", error_class: "invalid_configuration", items: [{ status: "failed", error_class: "invalid_configuration", error_detail: null }],
  }), { message: FALLBACK });
});

// Runs the real providerRequiresManualAttention against one freshness entry.
function requiresManualAttention(entry) {
  const start = statusSource.indexOf("const NON_RETRYABLE_PROVIDER_ERRORS");
  const end = statusSource.indexOf("function renderProviderAttention");
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({});
  vm.runInContext(statusSource.slice(start, end), context);
  context.entry = entry;
  return vm.runInContext("providerRequiresManualAttention(entry)", context);
}

test("a busy local database never asks for manual attention", () => {
  for (const state of ["error", "stale", "partial"]) {
    assert.equal(requiresManualAttention({ configured: true, state, error_code: "database_busy", next_retry_at: null }), false);
  }
});

test("a provider failure without a scheduled retry still asks for manual attention", () => {
  assert.equal(requiresManualAttention({ configured: true, state: "error", error_code: "network_error", next_retry_at: null }), true);
  assert.equal(requiresManualAttention({ configured: true, state: "stale", error_code: "auth_required", next_retry_at: null }), true);
});

// Runs the real manual sync actions with stubbed page helpers; `jobs` answers each job poll.
function syncHarness(jobs) {
  const posts = [];
  const toasts = [];
  const makeButton = () => ({ disabled: false, textContent: "", classList: { add() {}, remove() {} } });
  const context = vm.createContext({
    state: { localSync: {}, data: {}, route: "settings" },
    $: (selector) => (selector.startsWith("#") ? makeButton() : null),
    api: async (url, options) => {
      if (options?.method === "POST") { posts.push(url); return { id: "job-1" }; }
      return jobs[Math.min(posts.length - 1, jobs.length - 1)];
    },
    toast: (message, isError) => toasts.push({ message, isError }),
    load: async () => {},
    renderSettings: () => {},
    invalidateContextPreview: () => {},
    providerIds: () => ({ garmin: "garmin", wahoo: "wahoo", intervals: "intervals" }),
    AppApi: { messageForReason: (_reason, fallback) => fallback },
  });
  const start = statusSource.indexOf("const NON_RETRYABLE_PROVIDER_ERRORS");
  const end = statusSource.indexOf("function providerRequiresManualAttention");
  vm.runInContext(statusSource.slice(start, end), context);
  const retryStart = statusSource.indexOf("// Garmin and Wahoo set the local sync flag");
  const retryEnd = statusSource.length;
  assert.ok(retryStart >= 0 && retryEnd > retryStart);
  vm.runInContext(statusSource.slice(retryStart, retryEnd), context);
  vm.runInContext(actionsSource, context);
  return { context, posts, toasts };
}

test("a failed weather sync toast carries the job's redacted cause", async () => {
  const { context, toasts } = syncHarness([{
    id: "job-1", status: "failed", error_detail: "Open-Meteo antwortet nicht (HTTP 503).", items: [],
  }]);
  await vm.runInContext("syncWeather()", context);
  assert.deepEqual(toasts, [{ message: "Open-Meteo antwortet nicht (HTTP 503).", isError: true }]);
});

test("a failed sync without a cause keeps the generic message", async () => {
  const { context, toasts } = syncHarness([{ id: "job-1", status: "failed", items: [] }]);
  await vm.runInContext("syncGarmin()", context);
  assert.equal(toasts[0].message, "Garmin-Synchronisierung fehlgeschlagen.");
});

test("a second tap during a running sync starts no second job", async () => {
  for (const [action, flag] of [["syncGarmin", "garmin"], ["syncWahoo", "wahoo"], ["syncWeather", "weather"], ["syncExternalCalendar", "externalCalendar"]]) {
    const { context, posts } = syncHarness([{ id: "job-1", status: "completed", items: [] }]);
    context.state.localSync[flag] = true;
    await vm.runInContext(`${action}()`, context);
    assert.equal(posts.length, 0, action);
  }
});

test("retrying a stale Wahoo entry starts the Wahoo sync", async () => {
  const { context, posts } = syncHarness([{ id: "job-1", status: "completed", items: [] }]);
  await vm.runInContext("retryProvider('wahoo', null)", context);
  assert.deepEqual(posts, ["/api/wahoo/sync"]);
});

test("the retry is skipped while that provider's sync is running", async () => {
  const { context, posts } = syncHarness([{ id: "job-1", status: "completed", items: [] }]);
  context.state.localSync.garmin = true;
  await vm.runInContext("retryProvider('garmin', null)", context);
  assert.equal(posts.length, 0);
});
