const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function loadCadenceDisplay() {
  const source = fs.readFileSync(path.join(__dirname, "../public/activity-details.js"), "utf8").replace(/\r\n/g, "\n");
  const start = source.indexOf("  function cadenceDisplay(");
  assert.notEqual(start, -1, "cadenceDisplay must exist in activity-details.js");
  const end = source.indexOf("\n  }\n", start);
  const context = vm.createContext({});
  vm.runInContext(`${source.slice(start, end + 4)};globalThis.cadenceDisplay = cadenceDisplay;`, context);
  return context.cadenceDisplay;
}

test("foot sports show step frequency of both legs, other sports per-leg cadence", () => {
  const cadenceDisplay = loadCadenceDisplay();
  for (const sport of ["run", "walk", "hike"]) {
    assert.deepEqual({ ...cadenceDisplay({ sport }) }, { label: "Schrittfrequenz", unit: "spm", factor: 2 }, sport);
  }
  for (const sport of ["ride", "swim", "", undefined]) {
    assert.deepEqual({ ...cadenceDisplay({ sport }) }, { label: "Kadenz", unit: "rpm", factor: 1 }, String(sport));
  }
});
