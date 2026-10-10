const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/analysis.js"), "utf8");
const start = source.indexOf("function analysisWeekTickLabel(");
const end = source.indexOf("\nfunction appendAnalysisDateTicks(", start);

function loadTickLabels() {
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({});
  vm.runInContext(`${source.slice(start, end)};globalThis.analysisWeekTickLabel = analysisWeekTickLabel;globalThis.analysisDayTickLabel = analysisDayTickLabel;`, context);
  return { weekTickLabel: context.analysisWeekTickLabel, dayTickLabel: context.analysisDayTickLabel };
}

test("weekly ticks show a date from the displayed week", () => {
  const { weekTickLabel } = loadTickLabels();
  assert.equal(weekTickLabel("2026-10-05"), "05.10");
  assert.equal(weekTickLabel("2026-10-11"), "11.10");
  assert.equal(weekTickLabel("2025-12-29"), "29.12");
  assert.equal(weekTickLabel("2027-01-01"), "01.01");
  assert.equal(weekTickLabel("2026-12-31"), "31.12");
});

test("rolling seven-day buckets keep day-month date labels", () => {
  const { dayTickLabel } = loadTickLabels();
  assert.equal(dayTickLabel("2026-10-07"), "07.10");
  assert.equal(dayTickLabel("2026-10-10"), "10.10");
});
