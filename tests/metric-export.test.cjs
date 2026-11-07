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
  assert.match(off.text, /lokalen Zonen, sonst Garmin, sonst Wahoo/);
  assert.equal(off.button, "Werte automatisch an Intervals.icu senden");

  const on = loadFunctions({}, ["metricExportView"]).metricExportView(true);
  assert.match(on.text, /automatisch an Intervals\.icu/);
  assert.match(on.text, /HF-Zonen neu/);
  assert.match(on.text, /geschützt/);
  assert.equal(on.button, "Automatischen Abgleich deaktivieren");
});

test("the last sync receipt is shown as text and empty when absent", () => {
  const status = "Intervals.icu: 2 Werte gesendet, 1 Konflikte, 0 fehlgeschlagen.";
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

test("confirmed automatic consent names Intervals.icu and reloads state", async () => {
  const calls = [];
  const toasts = [];
  let loads = 0;
  const context = loadFunctions({
    requestConfirmation: async () => true,
    providerIds: () => ({ garmin: "garmin", intervals: "intervals" }),
    api: async (route, options) => { calls.push({ route, body: JSON.parse(options.body) }); return { changes: [{ key: "weight", label: "Gewicht", enabled: true }] }; },
    load: async () => { loads++; },
    toast: (message, error) => { assert.ok(!error, message); toasts.push(message); },
  }, ["configureAutomaticMetricExport", "metricExportReceipt"]);
  const button = { disabled: false };
  await context.configureAutomaticMetricExport(true, button);
  assert.deepEqual(calls, [{ route: "/api/metric-export/automatic", body: { enabled: true, confirmed: true, source: "garmin", provider: "intervals" } }]);
  assert.equal(loads, 1);
  assert.equal(button.disabled, false);
  assert.deepEqual(toasts, ["Intervals.icu-Abgleich: Gewicht an"]);
});

test("the field checkboxes show only while the export is enabled", () => {
  const { metricExportFieldsView } = loadFunctions({}, ["metricExportFieldsView"]);
  const fields = [{ key: "weight", label: "Gewicht", enabled: true }, { key: "ftp", label: "Rad-FTP", enabled: false }];
  assert.equal(metricExportFieldsView(false, fields).length, 0);
  assert.deepEqual(JSON.parse(JSON.stringify(metricExportFieldsView(true, fields))), [
    { key: "weight", label: "Gewicht", checked: true },
    { key: "ftp", label: "Rad-FTP", checked: false },
  ]);
});

test("the receipt names each changed field", () => {
  const { metricExportReceipt } = loadFunctions({}, ["metricExportReceipt"]);
  assert.equal(metricExportReceipt({ changes: [{ label: "Rad-FTP", enabled: true }, { label: "Gewicht", enabled: false }] }), "Intervals.icu-Abgleich: Rad-FTP an, Gewicht aus");
  assert.equal(metricExportReceipt({ changes: [] }), "Intervals.icu-Abgleich: keine Änderung");
});

function fieldContext(confirmed, calls, toasts) {
  return loadFunctions({
    state: { data: { garmin: { metric_export_fields: [{ key: "weight", label: "Gewicht", enabled: true }, { key: "ftp", label: "Rad-FTP", enabled: false }] } } },
    requestConfirmation: async (message) => { calls.push({ message }); return confirmed; },
    providerIds: () => ({ garmin: "garmin", intervals: "intervals" }),
    api: async (route, options) => { calls.push({ route, body: JSON.parse(options.body) }); return { changes: [{ label: "Rad-FTP", enabled: true }] }; },
    load: async () => {},
    toast: (message, error) => toasts.push({ message, error: Boolean(error) }),
    metricExportInputs: new Map(),
    metricExportFieldsBusy: false,
  }, ["changeMetricExportField", "metricExportReceipt", "setMetricExportFieldsBusy"]);
}

test("a confirmed field change sends the full field list and shows the receipt", async () => {
  const calls = [];
  const toasts = [];
  const input = { checked: true, disabled: false };
  await fieldContext(true, calls, toasts).changeMetricExportField({ key: "ftp", label: "Rad-FTP" }, input);
  assert.match(calls[0].message, /Rad-FTP künftig automatisch an Intervals\.icu senden/);
  assert.deepEqual(calls[1].body, { enabled: true, field: "ftp", field_enabled: true, confirmed: true, source: "garmin", provider: "intervals" });
  assert.deepEqual(toasts, [{ message: "Intervals.icu-Abgleich: Rad-FTP an", error: false }]);
  assert.equal(input.checked, true);
});

test("a declined field change sends nothing and restores the checkbox", async () => {
  const calls = [];
  const input = { checked: false, disabled: false };
  await fieldContext(false, calls, []).changeMetricExportField({ key: "weight", label: "Gewicht" }, input);
  assert.equal(calls.length, 1);
  assert.match(calls[0].message, /Damit endet der automatische Abgleich/);
  assert.equal(input.checked, true);
});

test("the toggle sends the opposite of the last loaded state", async () => {
  const calls = [];
  const context = loadFunctions({
    state: { data: { garmin: { metric_export_enabled: true } } },
    requestConfirmation: async () => true,
    providerIds: () => ({ garmin: "garmin", intervals: "intervals" }),
    api: async (route, options) => calls.push(JSON.parse(options.body)),
    load: async () => {},
    toast: (message, error) => assert.ok(!error, message),
  }, ["toggleMetricExport", "configureAutomaticMetricExport", "metricExportReceipt"]);
  context.toggleMetricExport({ disabled: false });
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(calls, [{ enabled: false, confirmed: true, source: "garmin", provider: "intervals" }]);
});
