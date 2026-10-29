const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const { providerCheckView } = require("../public/provider-checks.js");

const source = fs.readFileSync(path.join(__dirname, "../public/provider-checks.js"), "utf8");
const PROVIDERS = ["alpha", "beta", "gamma"];

function loadChecks(apiHandler) {
  const results = new Map();
  const buttons = new Map();
  const classes = new Map();
  for (const id of PROVIDERS) {
    results.set(id, { textContent: "", classList: { toggle: (_name, on) => classes.set(id, Boolean(on)) } });
    buttons.set(id, { dataset: { checkButton: id, ...(id === "beta" ? { checkGroup: "beta beta-card" } : {}) }, disabled: false, addEventListener(_type, handler) { this.click = handler; } });
  }
  const calls = [];
  const toasts = [];
  const context = {
    document: {
      querySelectorAll: () => [...buttons.values()],
      querySelector: (selector) => {
        const id = /"(\w+)"/.exec(selector)[1];
        return selector.includes("check-result") ? results.get(id) : buttons.get(id);
      },
    },
    api: (requestPath, options = {}) => {
      calls.push({ path: requestPath, method: options.method || "GET" });
      return apiHandler(requestPath, options);
    },
    toast: (message, isError) => toasts.push({ message, isError }),
    setTimeout: () => 0,
    clearTimeout: () => {},
    Date,
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { toasts, calls, results, buttons, classes, run: (code) => vm.runInContext(code, context) };
}

test("every status has a distinct view and only failures are flagged", () => {
  const statuses = ["not_configured", "unchecked", "success", "auth_failed", "rate_limited", "unavailable", "unsupported", "misconfigured", "busy", "unknown", "scope_missing"];
  const texts = new Set();
  for (const status of statuses) {
    const view = providerCheckView({ status, checked_at: null });
    texts.add(view.text);
    assert.equal(view.failed, ["auth_failed", "rate_limited", "unavailable", "unsupported", "misconfigured", "unknown", "scope_missing"].includes(status));
    assert.equal(view.disabled, status === "not_configured");
  }
  assert.equal(texts.size, statuses.length);
});

test("rejected credentials use the server guidance and never claim success", () => {
  const view = providerCheckView({ status: "auth_failed", guidance: "Bitte neu anmelden" });
  assert.match(view.text, /Bitte neu anmelden/);
  assert.doesNotMatch(view.text, /erfolgreich/);
  assert.equal(providerCheckView({ status: "auth_failed" }).text, "Anmeldung abgelehnt");
});

test("check time is shown only for a real timestamp; a missing result is neutral", () => {
  assert.match(providerCheckView({ status: "success", checked_at: "2026-01-02T03:04:05Z" }).text, /·/);
  assert.doesNotMatch(providerCheckView({ status: "success", checked_at: "invalid" }).text, /·/);
  const missing = providerCheckView(null);
  assert.match(missing.text, /nicht verfügbar/);
  assert.equal(missing.disabled, false);
});

test("passive load reads local status and never posts", async () => {
  const { run, calls, results, buttons } = loadChecks(async () => ({
    providers: { alpha: { status: "success", checked_at: null }, beta: { status: "not_configured", checked_at: null } },
  }));
  await run("loadProviderChecks()");
  assert.deepEqual(calls, [{ path: "/api/providers/connections", method: "GET" }]);
  assert.match(results.get("alpha").textContent, /Verbindung erfolgreich/);
  assert.equal(buttons.get("beta").disabled, true);
  assert.match(results.get("gamma").textContent, /nicht verfügbar/);
});

test("explicit check posts once, shows pending, and ignores a concurrent click", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { run, calls, results, buttons, classes } = loadChecks(async (_path, options) => {
    if (options.method !== "POST") return { providers: {} };
    await gate;
    return { status: "auth_failed", checked_at: "2026-01-02T03:04:05Z", guidance: "Anmeldung abgelehnt – Schlüssel prüfen" };
  });
  const first = run('checkProviderConnection("alpha")');
  assert.equal(results.get("alpha").textContent, "Verbindung wird geprüft…");
  assert.equal(buttons.get("alpha").disabled, true);
  await run('checkProviderConnection("alpha")');
  release();
  await first;
  assert.deepEqual(calls.filter((call) => call.method === "POST"), [{ path: "/api/providers/alpha/check", method: "POST" }]);
  assert.match(results.get("alpha").textContent, /Schlüssel prüfen/);
  assert.equal(classes.get("alpha"), true);
  assert.equal(buttons.get("alpha").disabled, false);
});

test("a failed request shows no body, keeps the previous result and the button usable", async () => {
  let fail = false;
  const { run, results, buttons, toasts } = loadChecks(async () => {
    if (fail) throw new Error("secret-body");
    return { providers: { gamma: { status: "success", checked_at: null } } };
  });
  await run("loadProviderChecks()");
  fail = true;
  await run('checkProviderConnection("gamma")');
  assert.doesNotMatch(results.get("gamma").textContent + JSON.stringify(toasts), /secret/);
  assert.match(results.get("gamma").textContent, /Verbindung erfolgreich/);
  assert.equal(toasts.length, 1);
  assert.equal(buttons.get("gamma").disabled, false);
  await run("loadProviderChecks()");
  assert.match(results.get("gamma").textContent, /Verbindung erfolgreich/);
});

test("a concurrent-check or busy answer does not replace the stored result", async () => {
  for (const status of ["checking", "busy"]) {
  const { run, results, toasts } = loadChecks(async (_path, options) => options.method === "POST"
    ? { status, checked_at: null }
    : { providers: { alpha: { status: "success", checked_at: null } } });
  await run("loadProviderChecks()");
  await run('checkProviderConnection("alpha")');
  assert.match(results.get("alpha").textContent, /Verbindung erfolgreich/);
  assert.equal(toasts.length, 1, "the athlete is told why nothing changed");
  }
});

test("a credential change drops an in-flight result and refreshes from the server", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { run, results, calls } = loadChecks(async (_path, options) => {
    if (options.method === "POST") {
      await gate;
      return { status: "success", checked_at: "2026-01-02T03:04:05Z" };
    }
    return { providers: { alpha: { status: "unchecked", checked_at: null } } };
  });
  const pending = run('checkProviderConnection("alpha")');
  run("invalidateProviderChecks()");
  release();
  await pending;
  await new Promise((resolve) => setImmediate(resolve));
  assert.match(results.get("alpha").textContent, /nicht geprüft/);
  assert.ok(calls.some((call) => call.method === "GET"));
});

test("invalidating without a group resets every provider until the server answers", async () => {
  const { run, results } = loadChecks(async () => ({
    providers: { alpha: { status: "success", checked_at: null }, beta: { status: "not_configured", checked_at: null } },
  }));
  await run("loadProviderChecks()");
  run("invalidateProviderChecks()");
  assert.match(results.get("alpha").textContent, /Status wird geladen/);
  assert.match(results.get("beta").textContent, /Status wird geladen/);
});

test("binding wires every check button to its provider", async () => {
  const { run, calls, buttons } = loadChecks(async () => ({ status: "success", checked_at: null }));
  run("bindProviderChecks()");
  await buttons.get("beta").click();
  assert.deepEqual(calls, [{ path: "/api/providers/beta/check", method: "POST" }]);
});

test("invalidating one provider leaves the others and enables a freshly configured one", async () => {
  const { run, results, buttons } = loadChecks(async () => ({
    providers: { alpha: { status: "success", checked_at: null }, beta: { status: "not_configured", checked_at: null } },
  }));
  await run("loadProviderChecks()");
  assert.equal(buttons.get("beta").disabled, true);
  run('invalidateProviderChecks("beta-card")');
  assert.match(results.get("alpha").textContent, /Verbindung erfolgreich/);
  assert.match(results.get("beta").textContent, /Status wird geladen/);
  assert.equal(buttons.get("beta").disabled, true);
});

test("a failed read after invalidation leaves no pending state behind", async () => {
  const { run, results, buttons } = loadChecks(async () => { throw new Error("offline"); });
  run('invalidateProviderChecks("beta")');
  await run("loadProviderChecks()");
  assert.match(results.get("beta").textContent, /nicht verfügbar/);
  assert.equal(buttons.get("beta").disabled, false);
});

test("a status read that started before a check cannot overwrite its result", async () => {
  let releaseLoad;
  const loadGate = new Promise((resolve) => { releaseLoad = resolve; });
  const { run, results } = loadChecks(async (_path, options) => {
    if (options.method === "POST") return { status: "success", checked_at: "2026-01-02T03:04:05Z" };
    await loadGate;
    return { providers: { alpha: { status: "unchecked", checked_at: null } } };
  });
  const load = run("loadProviderChecks()");
  await run('checkProviderConnection("alpha")');
  releaseLoad();
  await load;
  assert.match(results.get("alpha").textContent, /Verbindung erfolgreich/);
});

test("a status read started before a slow check still updates the other cards", async () => {
  let releaseLoad;
  const loadGate = new Promise((resolve) => { releaseLoad = resolve; });
  let releaseCheck;
  const checkGate = new Promise((resolve) => { releaseCheck = resolve; });
  const { run, results } = loadChecks(async (_path, options) => {
    if (options.method === "POST") { await checkGate; return { status: "success", checked_at: null }; }
    await loadGate;
    return { providers: { alpha: { status: "unchecked", checked_at: null }, beta: { status: "success", checked_at: null } } };
  });
  const load = run("loadProviderChecks()");
  const check = run('checkProviderConnection("alpha")');
  releaseCheck();
  await check;
  releaseLoad();
  await load;
  assert.match(results.get("alpha").textContent, /Verbindung erfolgreich/);
  assert.match(results.get("beta").textContent, /Verbindung erfolgreich/);
});

test("an explicit check announces its outcome and a failed request re-reads the server state", async () => {
  let fail = false;
  const { run, toasts, calls } = loadChecks(async (_path, options) => {
    if (options.method === "POST") {
      if (fail) throw new Error("timeout");
      return { status: "success", checked_at: null };
    }
    return { providers: { alpha: { status: "success", checked_at: null } } };
  });
  await run('checkProviderConnection("alpha")');
  assert.deepEqual(toasts.map((entry) => entry.isError), [false]);
  fail = true;
  await run('checkProviderConnection("alpha")');
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(toasts.length, 2);
  assert.ok(calls.some((call) => call.method === "GET"), "state is re-read after an aborted request");
});
