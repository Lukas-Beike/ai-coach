const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const SOURCE = fs.readFileSync(path.join(__dirname, "../public/performance-view.js"), "utf8").replace(/\r\n/g, "\n");
const NAMES = ["metricExportValue", "metricExportLine", "metricExportSummary", "metricExportRequest", "metricExportReceiptText", "exportCurrentMetrics"];

function load(globals = {}) {
  const chunks = NAMES.map((name) => {
    const start = SOURCE.search(new RegExp(`(?:async )?function ${name}\\(`));
    assert.notEqual(start, -1, `${name} must exist in performance-view.js`);
    const end = SOURCE.indexOf("\n}\n", start);
    return SOURCE.slice(start, end + 3);
  });
  const context = vm.createContext({
    analysisValue: (value, unit) => `${value} ${unit}`,
    dateLabel: (value) => `D:${value}`,
    ...globals,
  });
  vm.runInContext(chunks.join("\n"), context);
  return context;
}

const PREVIEW = {
  provider: "intervals",
  provider_label: "Intervals.icu",
  recalc_hr_zones_available: true,
  items: [
    { key: "weight|", metric: "weight", sport: null, value: 70.4, unit: "kg", observed_on: "2026-10-10", source_label: "Garmin Connect", target_label: "Wellness · weight", current_remote_value: 71.2, selectable: true },
    { key: "max_hr|run", metric: "max_hr", sport: "run", value: 191, unit: "bpm", observed_on: "2026-10-01", source_label: "", target_label: "Sporteinstellungen Lauf · max_hr", current_remote_value: null, selectable: true },
    { key: "ftp|ride", metric: "ftp", sport: "ride", value: 250, unit: "W", observed_on: "2026-09-01", source_label: "Garmin Connect", target_label: "Sporteinstellungen Rad · ftp", current_remote_value: 255, selectable: false },
  ],
};

test("the confirmation names the target, every value, its source, field and the current remote value", () => {
  const { metricExportSummary } = load();
  const items = PREVIEW.items.filter((item) => item.selectable);
  const summary = metricExportSummary(PREVIEW, items, false);
  const lines = summary.split("\n");
  assert.equal(lines[0], "Diese Werte werden an Intervals.icu gesendet. Nur die genannten Felder ändern sich.");
  assert.ok(lines.includes("• Gewicht: 70.4 kg vom D:2026-10-10 · Quelle: Garmin Connect → Wellness · weight (dort bisher 71.2 kg)"));
  assert.ok(lines.includes("• Maximale Herzfrequenz (Lauf): 191 bpm vom D:2026-10-01 · Quelle: unbekannt → Sporteinstellungen Lauf · max_hr (dort noch kein Wert)"));
  assert.ok(lines.includes("1 weitere Werte sind dort bereits aktuell oder neuer und werden nicht gesendet."));
  assert.equal(lines.at(-1), "Die Herzfrequenzzonen in Intervals.icu bleiben unverändert.");
  assert.equal(metricExportSummary(PREVIEW, items, true).split("\n").at(-1), "Intervals.icu berechnet die Herzfrequenzzonen neu.");
});

test("threshold pace is shown per kilometre", () => {
  const { metricExportValue } = load();
  assert.equal(metricExportValue(4, "m/s"), "250 s/km");
  assert.equal(metricExportValue(0, "m/s"), "0 m/s");
});

test("the execute request is confirmed, names the provider and sends only key, day and value", () => {
  const { metricExportRequest } = load();
  const request = metricExportRequest(PREVIEW, PREVIEW.items.slice(0, 1), true);
  assert.deepEqual(JSON.parse(JSON.stringify(request)), {
    confirmed: true,
    provider: "intervals",
    recalc_hr_zones: true,
    metrics: [{ key: "weight|", observed_on: "2026-10-10", value: 70.4 }],
  });
});

test("the receipt toast reports sent and failed values", () => {
  const { metricExportReceiptText } = load();
  assert.equal(metricExportReceiptText({ provider_label: "Intervals.icu", exported: 2, failed: 0 }), "2 Werte an Intervals.icu gesendet");
  assert.equal(metricExportReceiptText({ provider_label: "Intervals.icu", exported: 1, failed: 1 }), "1 Werte an Intervals.icu gesendet, 1 fehlgeschlagen");
});

function harness({ confirm, preview = PREVIEW }) {
  const calls = [];
  const toasts = [];
  const context = load({
    api: async (route, options) => {
      calls.push({ route, body: JSON.parse(options.body) });
      return route.endsWith("/preview") ? preview : { provider_label: "Intervals.icu", exported: 2, failed: 0 };
    },
    requestConfirmation: async () => confirm,
    toast: (message, isError) => toasts.push({ message, isError: Boolean(isError) }),
  });
  return { context, calls, toasts };
}

test("a declined confirmation never calls execute", async () => {
  const { context, calls } = harness({ confirm: false });
  const button = { disabled: false };
  await context.exportCurrentMetrics(button, { checked: true });
  assert.deepEqual(calls.map((call) => call.route), ["/api/metric-export/preview"]);
  assert.equal(button.disabled, false);
});

test("a confirmed export sends the selectable preview items and the zone option", async () => {
  const { context, calls, toasts } = harness({ confirm: true });
  await context.exportCurrentMetrics({ disabled: false }, { checked: true });
  assert.deepEqual(calls.map((call) => call.route), ["/api/metric-export/preview", "/api/metric-export/execute"]);
  assert.equal(calls[1].body.confirmed, true);
  assert.equal(calls[1].body.recalc_hr_zones, true);
  assert.deepEqual(calls[1].body.metrics.map((item) => item.key), ["weight|", "max_hr|run"]);
  assert.deepEqual(toasts, [{ message: "2 Werte an Intervals.icu gesendet", isError: false }]);
});

test("nothing new to send asks for no confirmation", async () => {
  const preview = { ...PREVIEW, items: PREVIEW.items.map((item) => ({ ...item, selectable: false })) };
  const { context, calls, toasts } = harness({ confirm: true, preview });
  await context.exportCurrentMetrics({ disabled: false }, { checked: false });
  assert.equal(calls.length, 1);
  assert.deepEqual(toasts, [{ message: "Keine neuen Werte für Intervals.icu.", isError: false }]);
});
