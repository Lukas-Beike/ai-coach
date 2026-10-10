const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/analysis.js"), "utf8");
const start = source.indexOf("function analysisIsoWeek(");
const end = source.indexOf("\nfunction appendAnalysisDateTicks(", start);

function loadTickLabel() {
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({});
  vm.runInContext(`${source.slice(start, end)};globalThis.analysisTickLabel = analysisTickLabel;`, context);
  return context.analysisTickLabel;
}

test("calendar-week ticks label the ISO week that contains the tick date", () => {
  const tickLabel = loadTickLabel();
  assert.equal(tickLabel("2026-10-05", true), "KW 41");
  assert.equal(tickLabel("2026-10-11", true), "KW 41");
  assert.equal(tickLabel("2025-12-29", true), "KW 1");
  assert.equal(tickLabel("2027-01-01", true), "KW 53");
  assert.equal(tickLabel("2026-12-31", true), "KW 53");
});

test("rolling seven-day buckets keep date labels unless calendar weeks are requested", () => {
  const tickLabel = loadTickLabel();
  assert.equal(tickLabel("2026-10-07", false), "07.10");
  assert.equal(tickLabel("2026-10-10"), "10.10");
});
