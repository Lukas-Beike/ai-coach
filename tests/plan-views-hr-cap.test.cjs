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

// #2447: each planned step names its target range from the zones of the unit's day.
test("a step range reads as a span, an open lowest or top zone, or a pace in min/km", () => {
  const { plannedStepRange, plannedDescriptionText, plannedStepExtent } = loadPublicScript(["format.js", "performance-view.js", "plan-views.js"]);
  // Exact step lengths: 30 s, 90 s, 55 min, 70 min, 400 m.
  assert.deepEqual([30, 90, 3300, 4200].map((size) => plannedStepExtent(size, "duration")), ["30 s", "1:30 min", "55 min", "1:10 h"]);
  assert.equal(plannedStepExtent(400, "distance"), "400 m");
  for (const [range, text] of [
    [{ unit: "bpm", min: 110, max: 128 }, "110–128 bpm"],
    [{ unit: "bpm", max: 109 }, "≤ 109 bpm"],
    [{ unit: "bpm", min: 155 }, "≥ 155 bpm"],
    [{ unit: "W", min: 210, max: 210 }, "210 W"],
    // 320 and 295 s/km: the slower end first; the lowest pace zone is slower than its limit.
    [{ unit: "s/km", min: 320, max: 295 }, "5:20–4:55 /km"],
    [{ unit: "s/km", max: 320 }, "≥ 5:20 /km"],
    [null, ""],
    [{ unit: "zone", min: 1 }, ""],
  ]) assert.equal(plannedStepRange(range), text);
  // The pane keeps only the free text of the description; the stored text is unchanged.
  assert.equal(plannedDescriptionText("Locker einrollen\n- 10m Z1 HR\nMain set 4x\n- 4m Z4 HR\n- 2m Z1 HR\nNicht überziehen."), "Locker einrollen\nNicht überziehen.");
  assert.equal(plannedDescriptionText("- 40m Z2 HR"), "");
  // As the parser reads them: "-10m" without a space is a step, "Hauptteil:4x" a repeat header.
  assert.equal(plannedDescriptionText("Einlaufen\n-10m Z1 HR\nHauptteil:4x\n- 4m Z4 HR"), "Einlaufen");
});
