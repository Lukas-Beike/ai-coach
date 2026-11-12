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

// Runs one manual sync with stable page elements and records what the athlete can observe:
// the request, the button while the job runs, the toasts, the reloads and the final button state.
function observedSync(action, { job, daysValue = "", syncDays, postResult = { id: "job-1" }, failPost = null } = {}) {
  const buttons = new Map();
  const button = (selector) => {
    if (!buttons.has(selector)) {
      const element = { disabled: false, textContent: "", busy: false, classList: { add: (name) => { element.busy = name === "busy" || element.busy; }, remove: (name) => { if (name === "busy") element.busy = false; } } };
      buttons.set(selector, element);
    }
    return buttons.get(selector);
  };
  const dirty = { removed: false };
  const log = { posts: [], toasts: [], loads: 0, invalidations: 0, renders: 0, whileRunning: null };
  const context = extractFunctions("sync-status.js", [...PROVIDER_ERRORS, "providerSyncKey", "providerSyncRunning", "retryProvider"], {
    state: { localSync: {}, data: { sync_settings: { garmin_days: syncDays } }, route: "settings" },
    $: (selector) => {
      if (selector === "#garminSyncDays") return { value: daysValue, removeAttribute: () => { dirty.removed = true; } };
      return selector.endsWith("Button") ? button(selector) : null;
    },
    api: async (url, options) => {
      if (options?.method === "POST") {
        if (failPost) throw new Error(failPost);
        log.whileRunning = Object.fromEntries([...buttons].map(([selector, element]) => [selector, { disabled: element.disabled, text: element.textContent, busy: element.busy }]));
        log.posts.push({ url, body: options.body });
        return postResult;
      }
      return job;
    },
    toast: (message, isError) => log.toasts.push({ message, isError: Boolean(isError) }),
    load: async () => { log.loads += 1; },
    renderSettings: () => { log.renders += 1; },
    invalidateContextPreview: () => { log.invalidations += 1; },
    providerIds: () => ({ garmin: "garmin", wahoo: "wahoo", intervals: "intervals" }),
    AppApi: { messageForReason: (_reason, fallback) => fallback },
  });
  loadPublicScript("sync-actions.js", context);
  return { context, log, buttons, dirty, run: () => vm.runInContext(`${action}()`, context) };
}

test("a Garmin sync sends the chosen days, shows progress and ends idle", async () => {
  const run = observedSync("syncGarmin", { job: { status: "completed" }, daysValue: "30", syncDays: 84 });
  await run.run();
  assert.deepEqual(run.log.posts, [{ url: "/api/garmin/sync", body: "{\"days\":\"30\"}" }]);
  assert.deepEqual(run.log.whileRunning["#garminSyncButton"], { disabled: true, text: "Garmin wird synchronisiert…", busy: false });
  assert.equal(run.dirty.removed, true);
  assert.deepEqual(run.log.toasts, [{ message: "Garmin synchronisiert", isError: false }]);
  assert.deepEqual([run.log.invalidations, run.log.loads, run.context.state.localSync.garmin], [1, 1, false]);
  const button = run.buttons.get("#garminSyncButton");
  assert.deepEqual([button.disabled, button.textContent], [false, "Garmin synchronisieren"]);
});

test("a Garmin sync falls back to the saved window and then to 84 days, and a partial job says so", async () => {
  const saved = observedSync("syncGarmin", { job: { status: "partial" }, syncDays: 42 });
  await saved.run();
  assert.equal(saved.log.posts[0].body, "{\"days\":42}");
  assert.equal(saved.log.toasts[0].message, "Garmin teilweise synchronisiert");
  const none = observedSync("syncGarmin", { job: { status: "completed" } });
  await none.run();
  assert.equal(none.log.posts[0].body, "{\"days\":84}");
});

test("a calendar sync shows progress, restores its label and reloads once", async () => {
  const run = observedSync("syncExternalCalendar", { job: { status: "partial" } });
  await run.run();
  assert.deepEqual(run.log.posts, [{ url: "/api/external-calendar/sync", body: "{}" }]);
  assert.deepEqual(run.log.whileRunning["#externalCalendarSyncButton"], { disabled: true, text: "Synchronisierung läuft…", busy: false });
  assert.deepEqual(run.log.toasts, [{ message: "Kalender teilweise synchronisiert", isError: false }]);
  assert.deepEqual([run.log.invalidations, run.log.loads, run.context.state.localSync.externalCalendar], [1, 1, false]);
  const button = run.buttons.get("#externalCalendarSyncButton");
  assert.deepEqual([button.disabled, button.textContent], [false, "Synchronisieren"]);
});

test("a weather sync pulses while it runs and redraws the settings afterwards", async () => {
  const run = observedSync("syncWeather", { job: { status: "completed" } });
  await run.run();
  assert.deepEqual(run.log.posts, [{ url: "/api/weather/sync", body: "{}" }]);
  assert.deepEqual(run.log.whileRunning["#weatherSyncButton"], { disabled: true, text: "Wetter wird aktualisiert…", busy: true });
  assert.deepEqual(run.log.toasts, [{ message: "Open-Meteo-Wetter aktualisiert", isError: false }]);
  assert.deepEqual([run.log.invalidations, run.log.loads, run.log.renders, run.context.state.localSync.weather, run.buttons.get("#weatherSyncButton").busy], [1, 1, 1, false, false]);
  const partial = observedSync("syncWeather", { job: { status: "partial" } });
  await partial.run();
  assert.equal(partial.log.toasts[0].message, "Open-Meteo teilweise aktualisiert");
});

test("a Wahoo sync shows progress, names its result and redraws the settings", async () => {
  const run = observedSync("syncWahoo", { job: { status: "completed" } });
  await run.run();
  assert.deepEqual(run.log.posts, [{ url: "/api/wahoo/sync", body: "{}" }]);
  assert.deepEqual(run.log.whileRunning["#wahooSyncButton"], { disabled: true, text: "Synchronisierung läuft…", busy: false });
  assert.deepEqual(run.log.toasts, [{ message: "Wahoo synchronisiert", isError: false }]);
  assert.deepEqual([run.log.invalidations, run.log.loads, run.log.renders, run.context.state.localSync.wahoo], [1, 1, 1, false]);
});

test("a Wahoo sync without a job id reports it and reloads", async () => {
  const run = observedSync("syncWahoo", { job: { status: "completed" }, postResult: {} });
  await run.run();
  assert.deepEqual(run.log.toasts, [{ message: "Die Jobbestätigung fehlt.", isError: true }]);
  assert.deepEqual([run.log.invalidations, run.log.loads, run.log.renders, run.context.state.localSync.wahoo], [0, 1, 1, false]);
});

test("a failed start request shows its error, reloads and frees the button", async () => {
  for (const [action, selector, label] of [["syncGarmin", "#garminSyncButton", "Garmin synchronisieren"], ["syncExternalCalendar", "#externalCalendarSyncButton", "Synchronisieren"], ["syncWeather", "#weatherSyncButton", null], ["syncWahoo", "#wahooSyncButton", null]]) {
    const run = observedSync(action, { job: { status: "completed" }, failPost: "Netzwerk weg" });
    await run.run();
    assert.deepEqual(run.log.toasts, [{ message: "Netzwerk weg", isError: true }], action);
    assert.deepEqual([run.log.invalidations, run.log.loads], [0, 1], action);
    assert.deepEqual(Object.values(run.context.state.localSync), [false], action);
    const button = run.buttons.get(selector);
    if (label) assert.deepEqual([button.disabled, button.textContent], [false, label], action);
    else assert.equal(run.log.renders, 1, action);
  }
});

test("a failed job toasts once, reloads once and skips the context refresh", async () => {
  const run = observedSync("syncExternalCalendar", { job: { status: "failed", reason: "x" } });
  await run.run();
  assert.deepEqual(run.log.toasts, [{ message: "Kalender-Synchronisierung fehlgeschlagen.", isError: true }]);
  assert.deepEqual([run.log.invalidations, run.log.loads], [0, 1]);
});

test("a sync without its button does nothing", async () => {
  const run = observedSync("syncGarmin", { job: { status: "completed" } });
  run.context.$ = () => null;
  await run.run();
  assert.deepEqual([run.log.posts.length, run.log.loads, run.context.state.localSync.garmin], [0, 0, undefined]);
});

// Runs one model or thinking-level select change the way the page binds it.
function observedSelectSave(save, failure = null) {
  const log = { requests: [], toasts: [], loads: 0, whileRunning: null };
  const select = { disabled: false, value: "gpt-x", selectedIndex: 1, options: [{ text: "Alt" }, { text: "Neu" }] };
  const context = extractFunctions("settings.js", ["saveSelectSetting"], {
    api: async (url, options) => {
      log.whileRunning = select.disabled;
      if (failure) throw new Error(failure);
      log.requests.push({ url, method: options.method, body: options.body });
      return {};
    },
    toast: (message, isError) => log.toasts.push({ message, isError: Boolean(isError) }),
    load: async () => { log.loads += 1; },
    event: { currentTarget: select },
  });
  extractFunctions("sync-actions.js", ["runAction"], context);
  return { log, select, run: () => vm.runInContext(save.code, context) };
}

const SELECT_SAVES = [
  { label: "model", code: 'saveSelectSetting(event, "model", "model", "Aktiv")', url: "/api/settings/model", body: "{\"model\":\"gpt-x\"}", toast: "Aktiv: Neu" },
  { label: "service tier", code: 'saveSelectSetting(event, "service-tier", "service_tier", "Geschwindigkeit")', url: "/api/settings/service-tier", body: "{\"service_tier\":\"gpt-x\"}", toast: "Geschwindigkeit: Neu" },
  { label: "thinking level", code: 'saveSelectSetting(event, "thinking-level", "thinking_level", "Thinking Level")', url: "/api/settings/thinking-level", body: "{\"thinking_level\":\"gpt-x\"}", toast: "Thinking Level: Neu" },
];

test("saving the model, speed or thinking level locks the select, names the active option and reloads", async () => {
  for (const save of SELECT_SAVES) {
    const run = observedSelectSave(save);
    await run.run();
    assert.deepEqual(run.log.requests, [{ url: save.url, method: "PUT", body: save.body }], save.label);
    assert.equal(run.log.whileRunning, true, save.label);
    assert.deepEqual(run.log.toasts, [{ message: save.toast, isError: false }], save.label);
    assert.deepEqual([run.log.loads, run.select.disabled], [1, false], save.label);
  }
});

test("a failed model, speed or thinking-level save shows the error, reloads and unlocks the select", async () => {
  for (const save of SELECT_SAVES) {
    const run = observedSelectSave(save, "Modell abgelehnt");
    await run.run();
    assert.deepEqual(run.log.toasts, [{ message: "Modell abgelehnt", isError: true }], save.label);
    assert.deepEqual([run.log.loads, run.select.disabled], [1, false], save.label);
  }
});
