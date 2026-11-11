const assert = require("node:assert/strict");
const fs = require("node:fs");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

const context = extractFunctions("analysis.js", ["providerMetricValue"]);

test("running tolerance reads the Garmin fixture score and supported aliases", () => {
  const [record] = JSON.parse(fs.readFileSync("tests/fixtures/providers/garmin/running_tolerance.json", "utf8"));
  assert.equal(context.providerMetricValue("running_tolerance", record), 72);
  for (const field of ["toleranceScore", "runningTolerance", "tolerance"]) {
    assert.equal(context.providerMetricValue("running_tolerance", { [field]: 0 }), 0);
    assert.equal(context.providerMetricValue("running_tolerance", { [field]: 72 }), 72);
    for (const value of [null, "72", NaN, Infinity]) {
      assert.equal(context.providerMetricValue("running_tolerance", { [field]: value }), undefined);
    }
  }
  assert.equal(context.providerMetricValue("running_tolerance", {}), undefined);
});
