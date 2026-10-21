const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/provider-connections.js"), "utf8");

// Runs the named top-level functions of provider-connections.js inside the given context.
function loadFunctions(context, names) {
  vm.createContext(context);
  for (const name of names) {
    const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
    vm.runInContext(source.slice(start, source.indexOf("\n}", start) + 2), context);
  }
  return context;
}

test("the export card explains consent in both states", () => {
  const off = loadFunctions({}, ["metricExportView"]).metricExportView(false);
  assert.match(off.text, /^Einmal aktivieren/);
  assert.equal(off.button, "Garmin → Intervals.icu automatisch abgleichen");

  const on = loadFunctions({}, ["metricExportView"]).metricExportView(true);
  assert.match(on.text, /automatisch an Intervals\.icu/);
  assert.match(on.text, /Herzfrequenzzonen bleiben/);
  assert.match(on.text, /geschützt/);
  assert.equal(on.button, "Automatischen Abgleich deaktivieren");
});

test("the last sync receipt is shown as text and empty when absent", () => {
  const status = "Intervals.icu: 2 Messwerte gesendet, 1 Konflikte, 0 fehlgeschlagen.";
  const view = loadFunctions({}, ["metricExportView"]);
  assert.equal(view.metricExportView(true, status).status, status);
  assert.equal(view.metricExportView(true).status, "");
});

test("declining consent never saves an automatic export setting", async () => {
  let calls = 0;
  const context = loadFunctions({ requestConfirmation: async () => false, api: async () => { calls++; } }, ["configureAutomaticMetricExport"]);
  await context.configureAutomaticMetricExport(true, { disabled: false });
  assert.equal(calls, 0);
});

test("confirmed automatic consent names Garmin and Intervals.icu and reloads state", async () => {
  const calls = [];
  let loads = 0;
  const context = loadFunctions({
    requestConfirmation: async () => true,
    providerIds: () => ({ garmin: "garmin", intervals: "intervals" }),
    api: async (route, options) => calls.push({ route, body: JSON.parse(options.body) }),
    load: async () => { loads++; },
    toast: (message) => assert.fail(message),
  }, ["configureAutomaticMetricExport"]);
  const button = { disabled: false };
  await context.configureAutomaticMetricExport(true, button);
  assert.deepEqual(calls, [{ route: "/api/metric-export/automatic", body: { enabled: true, confirmed: true, source: "garmin", provider: "intervals" } }]);
  assert.equal(loads, 1);
  assert.equal(button.disabled, false);
});

test("the toggle sends the opposite of the last loaded state", async () => {
  const calls = [];
  const context = loadFunctions({
    state: { data: { garmin: { metric_export_enabled: true } } },
    requestConfirmation: async () => true,
    providerIds: () => ({ garmin: "garmin", intervals: "intervals" }),
    api: async (route, options) => calls.push(JSON.parse(options.body)),
    load: async () => {},
    toast: (message) => assert.fail(message),
  }, ["toggleMetricExport", "configureAutomaticMetricExport"]);
  context.toggleMetricExport({ disabled: false });
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(calls, [{ enabled: false, confirmed: true, source: "garmin", provider: "intervals" }]);
});
