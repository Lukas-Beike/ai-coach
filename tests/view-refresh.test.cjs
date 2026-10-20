const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { test } = require("node:test");

const context = vm.createContext({});
vm.runInContext(fs.readFileSync("public/view-refresh.js", "utf8"), context);

function setup({ response, route = "nutrition/diary", request = { path: "/api/nutrition/refresh", body: { area: "diary", date: "2026-10-20" } }, reload = async () => {} } = {}) {
  const classes = new Set();
  const button = {
    disabled: false,
    classList: { add: (name) => classes.add(name), remove: (name) => classes.delete(name) },
    setAttribute() {},
    removeAttribute() {},
  };
  const status = { textContent: "" };
  const calls = [];
  const refresh = context.AppViewRefresh.create({
    api: async (...args) => { calls.push(args); return typeof response === "function" ? response() : response; },
    waitForJob: async (id) => { calls.push(["wait", id]); return { status: "complete" }; },
    getRoute: () => route,
    getRequest: () => request,
    reload: async (...args) => { calls.push(["reload", ...args]); await reload(...args); },
    button,
    status,
  });
  return { refresh, button, status, classes, calls, setRoute(value) { route = value; }, setRequest(value) { request = value; } };
}

test("posts the selected view and reloads after a synchronous successful response", async () => {
  const c = setup({ response: { status: "ok" } });
  await c.refresh();
  assert.equal(JSON.stringify(c.calls), JSON.stringify([
    ["/api/nutrition/refresh", { method: "POST", body: '{"area":"diary","date":"2026-10-20"}' }],
    ["reload", "nutrition/diary", { path: "/api/nutrition/refresh", body: { area: "diary", date: "2026-10-20" } }],
  ]));
  assert.equal(c.status.textContent, "Aktualisiert.");
  assert.equal(c.button.disabled, false);
  assert.equal(c.classes.has("busy"), false);
});

test("waits for a queued job and reports partial completion after reloading", async () => {
  const c = setup({ response: { job_id: "synthetic-job" } });
  c.calls.length = 0;
  c.refresh = context.AppViewRefresh.create({
    api: async () => ({ job_id: "synthetic-job" }),
    waitForJob: async (id) => { c.calls.push(["wait", id]); return { status: "partial" }; },
    getRoute: () => "nutrition/week",
    getRequest: () => ({ path: "/api/nutrition/refresh", body: { area: "week", days: 84 } }),
    reload: async (...args) => c.calls.push(["reload", ...args]),
    button: c.button,
    status: c.status,
  });
  await c.refresh();
  assert.deepEqual(c.calls.map((call) => call[0]), ["wait", "reload"]);
  assert.equal(c.status.textContent, "Teilweise aktualisiert.");
});

test("does not announce or reload when the route or selected request changed", async () => {
  const c = setup({ response: () => new Promise((resolve) => { c.resolve = resolve; }) });
  c.status.textContent = "";
  const pending = c.refresh();
  await Promise.resolve();
  c.setRequest({ path: "/api/nutrition/refresh", body: { area: "diary", date: "2026-10-19" } });
  c.resolve({ status: "ok" });
  await pending;
  assert.equal(c.calls.some(([kind]) => kind === "reload"), false);
  assert.equal(c.status.textContent, "");
});

test("keeps partial values and distinguishes already-running and failed responses", async () => {
  let reloads = 0;
  const partial = setup({ response: { status: "partial" }, reload: async () => { reloads += 1; } });
  await partial.refresh();
  assert.equal(reloads, 1);
  assert.equal(partial.status.textContent, "Teilweise aktualisiert.");

  const running = setup({ response: { status: "already_running" } });
  await running.refresh();
  assert.equal(running.status.textContent, "Aktualisierung läuft bereits.");
  assert.equal(running.calls.some(([kind]) => kind === "reload"), false);

  const failed = setup({ response: { status: "failed", error_detail: "temporary failure" } });
  await failed.refresh();
  assert.match(failed.status.textContent, /Aktualisierung fehlgeschlagen: temporary failure/);
  assert.equal(failed.calls.some(([kind]) => kind === "reload"), false);
});


test("reloads local product data and reports the local result truthfully", async () => {
  const c = setup({
    route: "nutrition/products",
    request: { path: "/api/nutrition/refresh", body: { area: "products" } },
    response: { status: "local" },
  });
  await c.refresh();
  assert.equal(c.calls.some(([kind]) => kind === "reload"), true);
  assert.equal(c.status.textContent, "Lokale Daten aktualisiert.");
});

test("nutrition product refresh reload preserves the selected search query", () => {
  const source = fs.readFileSync("public/nutrition.js", "utf8");
  assert.match(source, /loadNutritionProducts\(query, \{ background: true, throwOnError: true, refresh: true, expectedQuery: query \}\)/);
  assert.match(source, /if \(background && nutritionLookupResultShown && !refresh\) return;/);
  assert.match(source, /renderNutritionProducts\(result\.products \|\| \[\]\);\s*if \(!preserveLookup\) status\.textContent/);
  assert.match(source, /targetId: "#nutritionLookupResult"/);
  assert.match(source, /if \(!preserveLookup\) status\.textContent = "Produkte werden gesucht/);
  assert.match(source, /expectedQuery !== null && document\.querySelector\("#nutritionProductQuery"\)\.value\.trim\(\) !== expectedQuery/);
});


test("reports a refresh reload failure instead of announcing success", async () => {
  const c = setup({ response: { status: "ok" }, reload: async () => { throw new Error("view reload failed"); } });
  await c.refresh();
  assert.match(c.status.textContent, /Aktualisierung fehlgeschlagen: view reload failed/);
  assert.notEqual(c.status.textContent, "Aktualisiert.");
});

test("nutrition body refresh lets the server choose the athlete-local date", () => {
  const source = fs.readFileSync("public/nutrition.js", "utf8");
  assert.match(source, /area: "body" }/);
  assert.doesNotMatch(source, /area: "body", date: todayIso\(\)/);
});
