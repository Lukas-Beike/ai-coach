const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const { wahooConnectionView, wahooFullResyncView, safeWahooAuthorizeUrl } = require("../public/wahoo-connection.js");

const publicDir = path.join(__dirname, "../public");
const apiSource = fs.readFileSync(path.join(publicDir, "api.js"), "utf8");
const actionsSource = fs.readFileSync(path.join(publicDir, "sync-actions.js"), "utf8");

const renderSources = ["connection-status.js", "performance-view.js", "wahoo-connection.js"].map((name) => fs.readFileSync(path.join(publicDir, name), "utf8"));

function fakeButton(text = "") {
  const classes = new Set();
  const classList = {
    add: (name) => classes.add(name),
    remove: (name) => classes.delete(name),
    toggle: (name, force) => (force ? classes.add(name) : classes.delete(name)),
    contains: (name) => classes.has(name),
  };
  return { disabled: false, textContent: text, classList };
}

// Loads the real api.js request helper and sync-actions.js in one vm context. Only
// the browser globals the actions read (DOM lookup, cookie, dialogs, reloads) are
// stubbed; fetch records each call so the path, method and CSRF header can be checked.
function loadSyncActions(route) {
  const calls = [];
  const confirmations = [];
  const selectors = [];
  const toasts = [];
  const buttons = {
    "#garminFullResyncButton": fakeButton("Lokale Daten neu laden"),
    "#garminFullResyncStatus": fakeButton(),
    "#wahooSyncButton": fakeButton("Jetzt synchronisieren"),
    "#wahooFullResyncButton": fakeButton("Vollständig neu synchronisieren"),
    "#wahooFullResyncStatus": fakeButton(),
  };
  const context = {
    Headers, Response, AbortController, URL, setTimeout, clearTimeout,
    document: { cookie: "ic_csrf=csrf-token-1" },
    fetch: async (url, init) => {
      calls.push({ path: url, method: init.method, csrf: new Headers(init.headers).get("X-CSRF-Token"), body: init.body });
      const { status = 200, body } = route(url, init.method);
      return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    },
    $: (selector) => {
      selectors.push(selector);
      return buttons[selector] ?? null;
    },
    state: {
      localSync: {},
      data: {
        garmin: { available: true, configured: true },
        wahoo: { configured: true, connected: true },
        provider_resync: { garmin: { running: false }, wahoo: { running: false } },
      },
    },
    formatTime: (value) => value,
    providerIds: () => ({ intervals: "intervals", garmin: "garmin", wahoo: "wahoo" }),
    coachProviderLabel: (provider) => ({ intervals: "Intervals.icu", garmin: "Garmin", wahoo: "Wahoo" })[provider] || "Provider",
    requestConfirmation: async (message, options) => {
      confirmations.push({ message, title: options?.title, expectedText: options?.expectedText });
      return true;
    },
    providerErrorIsNonRetryable: () => false,
    toast: (message, isError = false) => toasts.push({ message, isError }),
    invalidateContextPreview() {},
    load: async () => {},
    renderSettings() {},
  };
  vm.createContext(context);
  vm.runInContext(apiSource, context);
  renderSources.forEach((source) => vm.runInContext(source, context));
  vm.runInContext("async function api(path, options = {}) { return globalThis.AppApi.request(path, options, () => {}); }", context);
  vm.runInContext(actionsSource, context);
  return { context, calls, confirmations, selectors, toasts, buttons };
}

const wahooJobRoute = (job) => (url) => {
  if (url === "/api/wahoo/sync") return { status: 202, body: { id: "job-w", status: "queued" } };
  if (url === "/api/sync/jobs/job-w") return { body: { id: "job-w", items: [], ...job } };
  return { status: 404, body: { error: "unexpected" } };
};

const authRequired = { provider: "wahoo", error_code: "auth_required" };

test("a server without Wahoo credentials is not configured and offers no action", () => {
  const view = wahooConnectionView({ wahoo: { configured: false, connected: false } });
  assert.equal(view.status, "Nicht konfiguriert");
  assert.equal(view.showSetupHint, true);
  assert.equal(view.canConnect, false);
  assert.equal(view.canDisconnect, false);
});

test("configured but not connected offers only Connect", () => {
  const view = wahooConnectionView({ wahoo: { configured: true, connected: false } });
  assert.equal(view.status, "Nicht verbunden");
  assert.equal(view.canConnect, true);
  assert.equal(view.canDisconnect, false);
  assert.equal(view.connectLabel, "Wahoo verbinden");
  assert.equal(view.showSetupHint, false);
});

test("connected offers only Disconnect and never exposes the scope", () => {
  const view = wahooConnectionView({ wahoo: { configured: true, connected: true, scope: "workouts_read" } });
  assert.equal(view.status, "Verbunden");
  assert.equal(view.ok, true);
  assert.equal(view.canConnect, false);
  assert.equal(view.canDisconnect, true);
  assert.ok(!JSON.stringify(view).includes("workouts_read"));
});

test("the card detail shows only the connection state, without a scope note", () => {
  const disconnected = wahooConnectionView({ wahoo: { configured: true, connected: false } });
  assert.equal(disconnected.detail, "");
  globalThis.AppFormat = { dateTime: () => "16.10.2026, 09:00" };
  try {
    const connected = wahooConnectionView({ wahoo: { configured: true, connected: true, connected_at: "2026-10-16T07:00:00Z" } });
    assert.equal(connected.detail, "Verbunden seit 16.10.2026, 09:00");
  } finally {
    delete globalThis.AppFormat;
  }
});

test("stored tokens stay disconnectable after the configuration was removed", () => {
  const view = wahooConnectionView({ wahoo: { configured: false, connected: true } });
  assert.equal(view.status, "Verbunden");
  assert.equal(view.canConnect, false);
  assert.equal(view.canDisconnect, true);
  assert.equal(view.showSetupHint, true);
});

test("a rejected token (auth_required freshness) asks for a reconnect", () => {
  const view = wahooConnectionView({
    wahoo: { configured: true, connected: false },
    provider_ids: { wahoo: "wahoo" },
    provider_freshness: [{ provider: "intervals", error_code: "auth_required" }, authRequired],
  });
  assert.equal(view.reconnect, true);
  assert.equal(view.status, "Erneute Verbindung erforderlich");
  assert.equal(view.connectLabel, "Wahoo erneut verbinden");
  assert.equal(view.canConnect, true);
});

test("an auth error of another provider or a connected Wahoo is not a reconnect", () => {
  assert.equal(wahooConnectionView({
    wahoo: { configured: true, connected: false },
    provider_freshness: [{ provider: "garmin", error_code: "auth_required" }],
  }).reconnect, false);
  assert.equal(wahooConnectionView({
    wahoo: { configured: true, connected: true },
    provider_freshness: [authRequired],
  }).reconnect, false);
});

test("missing state degrades to not configured", () => {
  assert.equal(wahooConnectionView({}).status, "Nicht konfiguriert");
  assert.equal(wahooConnectionView(undefined).canConnect, false);
});

test("only https authorize URLs are followed", () => {
  assert.equal(safeWahooAuthorizeUrl("https://api.wahooligan.com/oauth/authorize?x=1"), "https://api.wahooligan.com/oauth/authorize?x=1");
  assert.equal(safeWahooAuthorizeUrl("javascript:alert(1)"), null);
  assert.equal(safeWahooAuthorizeUrl("http://example.test/"), null);
  assert.equal(safeWahooAuthorizeUrl(""), null);
});

test("the manual sync button is offered only while Wahoo is connected", () => {
  assert.equal(wahooConnectionView({ wahoo: { configured: false, connected: false } }).canSync, false);
  assert.equal(wahooConnectionView({ wahoo: { configured: true, connected: false } }).canSync, false);
  assert.equal(wahooConnectionView({ wahoo: { configured: true, connected: true } }).canSync, true);
  assert.equal(wahooConnectionView({ wahoo: { configured: false, connected: true } }).canSync, true);
});

test("the full-resync line prefers a running status, then the error, then the last completion", () => {
  assert.deepEqual(wahooFullResyncView({ running: true, status: "Lade Einheiten…", last_error: null }, true), { text: "Lade Einheiten…", error: false });
  assert.deepEqual(wahooFullResyncView({ last_error: "Wahoo hat die Anfrage abgelehnt." }, false), { text: "Wahoo hat die Anfrage abgelehnt.", error: true });
  const idle = wahooFullResyncView({}, false);
  assert.equal(idle.error, false);
  assert.match(idle.text, /90 Tage/);
  assert.doesNotMatch(idle.text, /löschen/);
});

test("manual Wahoo sync posts an empty body with the CSRF token and waits for its job", async () => {
  const harness = loadSyncActions(wahooJobRoute({ status: "completed" }));
  await vm.runInContext("syncWahoo()", harness.context);
  assert.deepEqual(harness.calls[0], { path: "/api/wahoo/sync", method: "POST", csrf: "csrf-token-1", body: "{}" });
  assert.equal(harness.calls[1].path, "/api/sync/jobs/job-w");
  assert.equal(harness.calls[1].method, "GET");
  assert.deepEqual(harness.toasts.at(-1), { message: "Wahoo synchronisiert", isError: false });
});

test("a failed Wahoo sync job shows its redacted item detail", async () => {
  const harness = loadSyncActions(wahooJobRoute({
    status: "failed",
    items: [{ status: "failed", error_class: "auth_required", error_detail: "Wahoo-Anmeldung abgelaufen." }],
  }));
  await vm.runInContext("syncWahoo()", harness.context);
  assert.deepEqual(harness.toasts.at(-1), { message: "Wahoo-Anmeldung abgelaufen.", isError: true });
});

// A full-resync route: the POST starts the run, each GET reports `running` until `polls` have passed.
const fullResyncRoute = ({ provider, polls = 0, outcome = { status: "ok" }, started = { status: 202, body: { status: "started", operation_id: "op-1" } }, lastError = null }) => {
  let reads = 0;
  return (url, method) => {
    if (url !== `/api/${provider}/full-resync`) return { status: 404, body: { error: "unexpected" } };
    if (method === "POST") return started;
    reads += 1;
    const running = reads <= polls;
    return { body: { running, status: running ? "läuft" : null, last_resync_at: null, last_error: lastError, outcome: running ? null : { operation_id: "op-1", ...outcome } } };
  };
};

const idleState = {
  garmin: { text: "Lokale Daten neu laden", button: "#garminFullResyncButton", label: "Garmin" },
  wahoo: { text: "Vollständig neu synchronisieren", button: "#wahooFullResyncButton", label: "Wahoo" },
};

test("Wahoo full resync posts the confirmed request with CSRF and a confirmation that deletes nothing", async () => {
  const harness = loadSyncActions(fullResyncRoute({ provider: "wahoo" }));
  await vm.runInContext("fullResync('wahoo')", harness.context);
  assert.equal(harness.selectors[0], "#wahooFullResyncButton");
  assert.equal(harness.confirmations.length, 1);
  assert.match(harness.confirmations[0].message, /90 Tage/);
  assert.doesNotMatch(harness.confirmations[0].message, /löschen/);
  assert.match(harness.confirmations[0].title, /Wahoo/);
  assert.deepEqual(harness.calls[0], {
    path: "/api/wahoo/full-resync",
    method: "POST",
    csrf: "csrf-token-1",
    body: JSON.stringify({ confirm: "FULL_RESYNC" }),
  });
  assert.equal(harness.context.state.localSync.wahooFull, false);
});

test("Garmin full resync keeps its route and control and says it deletes nothing", async () => {
  const harness = loadSyncActions(fullResyncRoute({ provider: "garmin" }));
  await vm.runInContext("fullResync('garmin')", harness.context);
  assert.deepEqual(harness.calls.map((call) => call.path), ["/api/garmin/full-resync", "/api/garmin/full-resync"]);
  assert.deepEqual(harness.calls.map((call) => call.method), ["POST", "GET"]);
  assert.ok(harness.selectors.includes("#garminFullResyncButton"));
  // A-022: the server deletes no local data, so the text must not announce a deletion.
  assert.match(harness.confirmations[0].message, /Lokale Daten bleiben erhalten/);
  assert.doesNotMatch(harness.confirmations[0].message, /löschen/);
  assert.equal(harness.confirmations[0].expectedText, "Garmin");
});

for (const provider of ["garmin", "wahoo"]) {
  const idle = idleState[provider];

  test(`${provider}: after a completed full resync the button is idle again, without busy, disabled or pulse`, async () => {
    const harness = loadSyncActions(fullResyncRoute({ provider }));
    const button = harness.buttons[idle.button];
    await vm.runInContext(`fullResync('${provider}')`, harness.context);
    assert.equal(button.classList.contains("busy"), false);
    assert.equal(button.disabled, false);
    assert.equal(button.textContent, idle.text);
    assert.deepEqual(harness.toasts.at(-1), { message: `${idle.label} vollständig neu geladen`, isError: false });
  });

  test(`${provider}: settling redraws the regular sync controls with the full-resync flag cleared`, async () => {
    const harness = loadSyncActions(fullResyncRoute({ provider }));
    const flags = [];
    harness.context.renderSettings = () => flags.push(harness.context.state.localSync[`${provider}Full`]);
    await vm.runInContext(`fullResync('${provider}')`, harness.context);
    assert.equal(flags.at(-1), false);
  });

  test(`${provider}: the button pulses and shows the running label while the resync runs`, async () => {
    const harness = loadSyncActions(fullResyncRoute({ provider, polls: 1 }));
    const button = harness.buttons[idle.button];
    const run = vm.runInContext(`fullResync('${provider}')`, harness.context);
    await new Promise((resolve) => setTimeout(resolve, 50));
    assert.equal(button.classList.contains("busy"), true);
    assert.equal(button.disabled, true);
    assert.equal(button.textContent, "Vollständiger Resync läuft…");
    await run;
    assert.equal(button.classList.contains("busy"), false);
    assert.equal(button.textContent, idle.text);
  });

  test(`${provider}: a partial result says "teilweise geladen" and a failed one shows the stored error`, async () => {
    const partial = loadSyncActions(fullResyncRoute({ provider, outcome: { status: "partial" } }));
    await vm.runInContext(`fullResync('${provider}')`, partial.context);
    assert.deepEqual(partial.toasts.at(-1), { message: `${idle.label} teilweise geladen`, isError: false });
    assert.equal(partial.buttons[idle.button].classList.contains("busy"), false);

    const failed = loadSyncActions(fullResyncRoute({ provider, outcome: { status: "failed" }, lastError: "Anbieter nicht erreichbar." }));
    await vm.runInContext(`fullResync('${provider}')`, failed.context);
    assert.deepEqual(failed.toasts.at(-1), { message: "Anbieter nicht erreichbar.", isError: true });
    assert.equal(failed.buttons[idle.button].disabled, false);
  });

  test(`${provider}: a repeated start reports "läuft bereits" and ends with the finished run, not an error`, async () => {
    const harness = loadSyncActions(fullResyncRoute({ provider, started: { status: 200, body: { status: "already_running", operation_id: "op-1" } } }));
    await vm.runInContext(`fullResync('${provider}')`, harness.context);
    assert.deepEqual(harness.toasts[0], { message: `${idle.label} läuft bereits`, isError: false });
    assert.equal(harness.toasts.some((toast) => toast.isError), false);
    assert.equal(harness.buttons[idle.button].classList.contains("busy"), false);
  });
}

test("a slow resync is polled, not reported as a failure, even when a single poll fails", async () => {
  let reads = 0;
  const route = (_url, method) => {
    if (method === "POST") return { status: 202, body: { status: "started", operation_id: "op-1" } };
    reads += 1;
    if (reads === 1) return { status: 502, body: { error: "gateway" } };
    const running = reads < 3;
    return { body: { running, outcome: running ? null : { operation_id: "op-1", status: "ok" }, last_error: null } };
  };
  const harness = loadSyncActions(route);
  await vm.runInContext("fullResync('garmin')", harness.context);
  assert.equal(harness.toasts.some((toast) => toast.isError), false);
  assert.deepEqual(harness.toasts.at(-1), { message: "Garmin vollständig neu geladen", isError: false });
});

test("a page opened during a running resync follows it and ends idle", async () => {
  const harness = loadSyncActions(fullResyncRoute({ provider: "garmin" }));
  harness.context.state.data.provider_resync.garmin.running = true;
  vm.runInContext("renderGarminFullResync(state.data)", harness.context);
  const button = harness.buttons["#garminFullResyncButton"];
  assert.equal(button.classList.contains("busy"), true);
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.equal(harness.context.state.localSync.garminFull, false);
  assert.equal(button.classList.contains("busy"), false);
  assert.equal(harness.calls.filter((call) => call.method === "POST").length, 0);
});
