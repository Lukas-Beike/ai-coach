const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

function loadCadenceDisplay() {
  return extractFunctions("activity-details.js", ["cadenceDisplay"]).cadenceDisplay;
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
