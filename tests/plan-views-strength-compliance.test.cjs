const assert = require("node:assert/strict");
const { test } = require("node:test");
const { loadPublicScript, FakeElement, fakeDocument } = require("./frontend-harness.cjs");

const { appendPlannedEntryStatus } = loadPublicScript(["performance-view.js", "plan-views.js"], { AppFormat: require("../public/format.js"), document: fakeDocument() });
const completed = (compliance) => ({ compliance: { ...compliance, actual_activity: { id: "a1" } } });

test("a strength unit compared by sets shows its share of the plan in the status", () => {
  const line = new FakeElement();
  appendPlannedEntryStatus(line, completed({ basis: "strength_sets", percentage: 75 }), "completed", null, "2026-11-10", "2026-11-11", true);
  assert.equal(line.children[0].textContent, "✓ Absolviert · 75 %");
});

test("an unknown basis shows the status without a share", () => {
  const line = new FakeElement();
  appendPlannedEntryStatus(line, completed({ basis: "unavailable", percentage: 100 }), "completed", null, "2026-11-10", "2026-11-11", true);
  assert.equal(line.children[0].textContent, "✓ Absolviert");
});
