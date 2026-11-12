const assert = require("node:assert/strict");
const vm = require("node:vm");
const { test } = require("node:test");
const { extractFunctions, loadPublicScript, FakeElement, fakeDocument } = require("./frontend-harness.cjs");

const PROVIDER_ERRORS = ["NON_RETRYABLE_PROVIDER_ERRORS", "TRANSIENT_LOCAL_PROVIDER_ERRORS", "providerErrorIsNonRetryable"];

// Runs the real waitForSyncJob against one terminal job DTO; non-retryable errors
// throw before any polling delay, so the test does not wait.
function waitForJob(job) {
  const context = extractFunctions("sync-status.js", PROVIDER_ERRORS, { api: async () => job });
  loadPublicScript("sync-actions.js", context);
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
  return extractFunctions("sync-status.js", [...PROVIDER_ERRORS, "providerRequiresManualAttention"]).providerRequiresManualAttention(entry);
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
  const context = extractFunctions("sync-status.js", [...PROVIDER_ERRORS, "providerSyncKey", "providerSyncRunning", "retryProvider"], {
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
  loadPublicScript("sync-actions.js", context);
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

test("retrying a stale weather or calendar entry starts that sync", async () => {
  for (const [provider, url] of [["weather", "/api/weather/sync"], ["calendar", "/api/external-calendar/sync"]]) {
    const { context, posts } = syncHarness([{ id: "job-1", status: "completed", items: [] }]);
    await vm.runInContext(`retryProvider('${provider}', null)`, context);
    assert.deepEqual(posts, [url], provider);
  }
});

test("the retry is skipped while that provider's sync is running", async () => {
  const { context, posts } = syncHarness([{ id: "job-1", status: "completed", items: [] }]);
  context.state.localSync.garmin = true;
  await vm.runInContext("retryProvider('garmin', null)", context);
  assert.equal(posts.length, 0);
});

test("provider labels come from the bootstrap and fall back to a neutral word", () => {
  const labelled = extractFunctions("sync-status.js", ["coachProviderLabel"], { state: { data: { provider_labels: { garmin: "Garmin Connect" } } } });
  assert.equal(labelled.coachProviderLabel(" Garmin "), "Garmin Connect");
  assert.equal(labelled.coachProviderLabel("wahoo"), "Provider");
  const unloaded = extractFunctions("sync-status.js", ["coachProviderLabel"], { state: { data: null } });
  assert.equal(unloaded.coachProviderLabel("garmin"), "Provider");
});

// Runs the real connection progress list against one bootstrap payload.
function connectionProgress(data, localSync = {}) {
  const document = fakeDocument();
  const root = document.querySelector("#connectionsSyncProgress");
  document.createElement = (tag) => Object.assign(new FakeElement(tag), { removeAttribute(name) { delete this.attributes[name]; } });
  extractFunctions("sync-status.js", ["connectionProgressEntry", "coachProviderLabel", "renderConnectionsSyncProgress"], {
    document,
    $: (selector) => document.querySelector(selector),
    state: { localSync, data: { provider_labels: { garmin: "Garmin", wahoo: "Wahoo" } } },
    providerIds: () => ({ garmin: "garmin", wahoo: "wahoo" }),
    garminWindowProgress: () => null,
  }).renderConnectionsSyncProgress(data);
  return root;
}

const itemText = (item) => item.children[0].children.map((node) => node.textContent).join(" | ");

test("the connection progress list stays hidden while nothing syncs", () => {
  assert.equal(connectionProgress({}).hidden, true);
});

test("a queued job waits without a percentage and a running job shows its completed steps", () => {
  const root = connectionProgress({ sync: { jobs: [
    { status: "queued", provider: "garmin" },
    { status: "running", provider: "wahoo", progress: { completed: 1, total: 4 } },
    { status: "completed", provider: "weather" },
  ] } });
  assert.equal(root.hidden, false);
  assert.deepEqual(root.children.map(itemText), ["Garmin | Wartet auf den Start der Synchronisierung…", "Wahoo | 1/4 Arbeitsschritte abgeschlossen"]);
  const [queued, running] = root.children.map((item) => item.children[1]);
  assert.match(queued.className, /is-indeterminate/);
  assert.equal(queued.attributes["aria-label"], "Garmin: Fortschritt wird ermittelt");
  assert.deepEqual([running.value, running.attributes["aria-label"]], [25, "Wahoo: 25%"]);
});

test("a local sync is listed once even when its job is also running", () => {
  const root = connectionProgress({ sync: { jobs: [{ status: "running", provider: "weather" }] } }, { weather: true });
  assert.deepEqual(root.children.map(itemText), ["Open-Meteo | Wetter wird aktualisiert…"]);
});
