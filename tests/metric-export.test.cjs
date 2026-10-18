const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/performance-view.js"), "utf8");
const start = source.indexOf("function metricExportActions()");
const end = source.indexOf("\n}", start) + 2;

function render(status) {
  const context = vm.createContext({
    state: { data: { garmin: { metric_export_status: status, metric_export_enabled: true } } },
    reportNode: (tag, text, className) => ({ tag, text, className, addEventListener() {}, children: [], append(node) { this.children.push(node); } }),
  });
  vm.runInContext(source.slice(start, end), context);
  return context.metricExportActions();
}

test("current metrics explain automatic transfer with a consent control", () => {
  const node = render(null);
  assert.equal(node.tag, "div");
  assert.equal(node.children.length, 2);
  assert.equal(node.children[0].tag, "p");
  assert.match(node.children[0].text, /automatisch an Intervals\.icu/);
  assert.match(node.children[0].text, /Herzfrequenzzonen bleiben/);
  assert.match(node.children[0].text, /geschützt/);
});

test("declining consent never saves an automatic export setting", async () => {
  const functionStart = source.indexOf("async function configureAutomaticMetricExport(");
  let calls = 0;
  const context = vm.createContext({ requestConfirmation: async () => false, api: async () => { calls++; } });
  vm.runInContext(source.slice(functionStart, source.indexOf("\n}", functionStart) + 2), context);
  await context.configureAutomaticMetricExport(true, { disabled: false });
  assert.equal(calls, 0);
});

test("confirmed automatic consent names Garmin and Intervals.icu and reloads state", async () => {
  const functionStart = source.indexOf("async function configureAutomaticMetricExport(");
  const calls = [];
  let loads = 0;
  const context = vm.createContext({
    requestConfirmation: async () => true,
    providerIds: () => ({ garmin: "garmin", intervals: "intervals" }),
    api: async (route, options) => calls.push({ route, body: JSON.parse(options.body) }),
    load: async () => { loads++; },
    toast: (message) => assert.fail(message),
  });
  vm.runInContext(source.slice(functionStart, source.indexOf("\n}", functionStart) + 2), context);
  const button = { disabled: false };
  await context.configureAutomaticMetricExport(true, button);
  assert.deepEqual(calls, [{ route: "/api/metric-export/automatic", body: { enabled: true, confirmed: true, source: "garmin", provider: "intervals" } }]);
  assert.equal(loads, 1);
  assert.equal(button.disabled, false);
});

test("the last sync receipt is rendered as text", () => {
  const status = "Intervals.icu: 2 Messwerte gesendet, 1 Konflikte, 0 fehlgeschlagen.";
  const node = render(status);
  assert.equal(node.children.length, 3);
  assert.equal(node.children[2].tag, "p");
  assert.equal(node.children[2].text, status);
});
