const assert = require("node:assert/strict");
const { test } = require("node:test");
const { loadPublicScript } = require("./frontend-harness.cjs");

const { hrCapChipSpec } = loadPublicScript(["performance-view.js", "plan-views.js"]);

// The numbers come from the entry; nothing here knows a cap table.
test("the cap reads as percent first, then the currently resolved bpm, then the source", () => {
  const stored = { percent_lthr: 12.5, low_percent_lthr: 8, source: "default" };
  assert.equal(hrCapChipSpec({ hr_cap: stored, hr_cap_bpm: { low: 99, high: 321 } }).text, "≤ 12.5 % LSHF · 321 bpm · Standard");
  assert.equal(
    hrCapChipSpec({ hr_cap: { ...stored, source: "measured" }, hr_cap_bpm: { low: 1, high: 77 } }).text,
    "≤ 12.5 % LSHF · 77 bpm · gemessen",
  );
});

test("the bpm follows the resolved value without any edit of the stored percent", () => {
  const stored = { percent_lthr: 40, low_percent_lthr: 20, source: "default" };
  assert.equal(hrCapChipSpec({ hr_cap: stored, hr_cap_bpm: { low: 1, high: 100 } }).text.includes("100 bpm"), true);
  assert.equal(hrCapChipSpec({ hr_cap: stored, hr_cap_bpm: { low: 1, high: 104 } }).text.includes("104 bpm"), true);
});

test("without a resolved bpm only the percent is shown, and a unit without a usable cap shows none", () => {
  assert.equal(hrCapChipSpec({ hr_cap: { percent_lthr: 40, low_percent_lthr: 20, source: "default" } }).text, "≤ 40 % LSHF · Standard");
  assert.equal(hrCapChipSpec({}), null);
  assert.equal(hrCapChipSpec({ hr_cap: null }), null);
  assert.equal(hrCapChipSpec({ hr_cap: { percent_lthr: "x", source: "default" } }), null);
  assert.equal(hrCapChipSpec({ hr_cap: { percent_lthr: 50 } }), null);
});
