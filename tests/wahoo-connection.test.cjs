const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const { wahooConnectionView, wahooFullResyncView, safeWahooAuthorizeUrl } = require("../public/wahoo-connection.js");

const publicDir = path.join(__dirname, "../public");
const apiSource = fs.readFileSync(path.join(publicDir, "api.js"), "utf8");
const actionsSource = fs.readFileSync(path.join(publicDir, "sync-actions.js"), "utf8");

function fakeButton() {
  return { disabled: false, textContent: "", classList: { add() {}, remove() {}, toggle() {} } };
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
    "#systemIntervalsFullResyncButton": fakeButton(),
    "#garminFullResyncButton": fakeButton(),
    "#wahooSyncButton": fakeButton(),
    "#wahooFullResyncButton": fakeButton(),
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
    state: { localSync: {}, data: {} },
    providerIds: () => ({ intervals: "intervals", garmin: "garmin", wahoo: "wahoo" }),
    coachProviderLabel: (provider) => ({ intervals: "Intervals.icu", garmin: "Garmin", wahoo: "Wahoo" })[provider] || "Provider",
    requestConfirmation: async (message, options) => {
      confirmations.push({ message, title: options?.title });
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
  vm.runInContext("async function api(path, options = {}) { return globalThis.AppApi.request(path, options, () => {}); }", context);
  vm.runInContext(actionsSource, context);
  return { context, calls, confirmations, selectors, toasts };
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

test("Wahoo full resync posts the confirmed request with CSRF and a confirmation that deletes nothing", async () => {
  const harness = loadSyncActions(() => ({ body: { status: "ok", source: "wahoo" } }));
  await vm.runInContext("fullResync('wahoo')", harness.context);
  assert.equal(harness.selectors[0], "#wahooFullResyncButton");
  assert.equal(harness.confirmations.length, 1);
  assert.match(harness.confirmations[0].message, /90 Tage/);
  assert.doesNotMatch(harness.confirmations[0].message, /löschen/);
  assert.match(harness.confirmations[0].title, /Wahoo/);
  assert.deepEqual(harness.calls, [{
    path: "/api/wahoo/full-resync",
    method: "POST",
    csrf: "csrf-token-1",
    body: JSON.stringify({ confirm: "FULL_RESYNC" }),
  }]);
  assert.equal(harness.context.state.localSync.wahooFull, false);
});

test("Garmin and Intervals.icu full resync keep their routes, controls and deletion wording", async () => {
  const harness = loadSyncActions(() => ({ body: { status: "ok" } }));
  await vm.runInContext("fullResync('garmin')", harness.context);
  await vm.runInContext("fullResync('intervals')", harness.context);
  assert.deepEqual(harness.calls.map((call) => call.path), ["/api/garmin/full-resync", "/api/intervals/full-resync"]);
  assert.ok(harness.selectors.includes("#garminFullResyncButton"));
  assert.ok(harness.selectors.includes("#systemIntervalsFullResyncButton"));
  assert.match(harness.confirmations[0].message, /löschen/);
  assert.match(harness.confirmations[1].message, /löschen/);
});
