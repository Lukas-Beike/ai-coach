const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function loadHelpers() {
  const source = fs.readFileSync(path.join(__dirname, "../public/activity-details.js"), "utf8").replace(/\r\n/g, "\n");
  const start = source.indexOf("  const RUNNING_DYNAMICS = [");
  const end = source.indexOf("  function renderRunningForm(");
  assert.notEqual(start, -1, "RUNNING_DYNAMICS must exist in activity-details.js");
  assert.notEqual(end, -1, "renderRunningForm must exist in activity-details.js");
  const context = vm.createContext({});
  vm.runInContext(`${source.slice(start, end)};globalThis.helpers = { runningDynamics, formDriftLines };`, context);
  return context.helpers;
}

const plain = (value) => JSON.parse(JSON.stringify(value));
const { runningDynamics, formDriftLines } = loadHelpers();

test("running dynamics show only the averages a sensor measured, with their units", () => {
  const rows = plain(runningDynamics({
    ground_contact_time_ms: 264.5,
    ground_contact_balance_pct: 49.63,
    vertical_ratio_pct: 8.04,
    step_length_m: 1.1636,
    avg_hr: 142,
  }));
  assert.deepEqual(rows, [
    ["Bodenkontaktzeit", "265 ms"],
    ["Bodenkontakt links", "49,6 %"],
    ["Vertikales Verhältnis", "8,0 %"],
    ["Schrittlänge", "1,16 m"],
  ]);
});

test("a run without running dynamics shows nothing and does not fail", () => {
  assert.deepEqual(plain(runningDynamics({})), []);
  assert.deepEqual(plain(runningDynamics(undefined)), []);
  assert.deepEqual(plain(runningDynamics({ ground_contact_time_ms: null, step_length_m: "1.2", vertical_ratio_pct: NaN })), []);
});

const metrics = {
  contact_time: { first: 250, last: 265, unit: "ms", change_percent: 6, exceeds: true },
  vertical_oscillation: { first: 9, last: 9.45, unit: "cm", change_percent: 5, exceeds: false },
  step_length: { first: 1.2, last: 1.16, unit: "m", change_percent: -3.33, exceeds: false },
};

test("a flagged form drift leads with its label and lists the changes", () => {
  const lines = plain(formDriftLines({ status: "ok", flagged: true, label: "Laufstil lässt nach", metrics }));
  assert.deepEqual(lines, [
    "Laufstil lässt nach",
    "Bodenkontaktzeit 250 → 265 ms (+6,0 %)",
    "Vertikale Oszillation 9,0 → 9,5 cm (+5,0 %)",
    "Schrittlänge 1,20 → 1,16 m (-3,3 %)",
  ]);
});

test("an unflagged form drift lists the changes without the label", () => {
  const lines = plain(formDriftLines({ status: "ok", flagged: false, label: null, metrics: { contact_time: metrics.contact_time } }));
  assert.deepEqual(lines, ["Bodenkontaktzeit 250 → 265 ms (+6,0 %)"]);
});

test("a form drift check that did not run shows nothing", () => {
  for (const drift of [undefined, null, {}, { status: "insufficient_data", reason: "Keine Laufdynamik aufgezeichnet." }]) {
    assert.deepEqual(plain(formDriftLines(drift)), []);
  }
  assert.deepEqual(plain(formDriftLines({ status: "ok", flagged: false, metrics: { contact_time: { first: "x" } } })), []);
});

test("the analysis list panel renders the drift lines through the shared helper", () => {
  const source = fs.readFileSync(path.join(__dirname, "../public/activity-analysis.js"), "utf8");
  assert.match(source, /ActivityDetails\.formDriftLines\(payload\?\.analysis\?\.form_drift\)/);
  assert.match(source, /ActivityDetails\.runningDynamics\(metrics\)/);
});
