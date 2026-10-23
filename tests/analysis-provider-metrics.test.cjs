const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync("public/analysis.js", "utf8");
const start = source.indexOf("function providerMetricValue(");
const end = source.indexOf("function renderProviderMetrics(", start);
const context = vm.createContext({});
vm.runInContext(source.slice(start, end), context);

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
