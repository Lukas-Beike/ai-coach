const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/analysis.js"), "utf8");
const start = source.indexOf("function seasonPlannedLoadEstimateNotes");
const end = source.indexOf("\nfunction ", start + 1);

function notes(result) {
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({
    reportNode(tag, text, className) { return { tag, text, className }; },
    dateLabel(value) { return `D:${value}`; },
  });
  vm.runInContext(source.slice(start, end), context);
  return context.seasonPlannedLoadEstimateNotes(result).map((node) => node.text);
}

test("scenarios without estimated planned load show no estimate note", () => {
  assert.equal(notes({ planned_load_estimated: false, estimated_planned_units: [] }).length, 0);
  assert.equal(notes({}).length, 0);
});

test("estimated planned load is labelled with its source and the affected units", () => {
  const [summary, units] = notes({
    planned_load_estimated: true,
    estimated_planned_units: [{ date: "2026-10-03", name: "Tempo", load: 72.25 }],
  });
  assert.match(summary, /teilweise geschätzt \(Quelle: Schätzung aus geplanter Dauer und Zielintensität\): 1 Einheit$/);
  assert.equal(units, "Geschätzte Einheiten: D:2026-10-03 Tempo (Belastung ≈ 72)");
});

test("more than three estimated units are shortened", () => {
  const unit = (day) => ({ date: `2026-10-0${day}`, name: `U${day}`, load: 10 });
  const [summary, units] = notes({ planned_load_estimated: true, estimated_planned_units: [1, 2, 3, 4].map(unit) });
  assert.match(summary, /: 4 Einheiten$/);
  assert.match(units, /U3 \(Belastung ≈ 10\) · …$/);
  assert.doesNotMatch(units, /U4/);
});
