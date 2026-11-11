const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions, fakeDocument } = require("./frontend-harness.cjs");

const context = extractFunctions("nutrition.js", ["nutritionTotalTile"], { document: fakeDocument(), todayIso: () => "2026-11-02", nutritionNumber: String, setValueWithUnit: (node, text) => { node.textContent = text; } });

test("marks complete values outside a range and avoids premature low warnings", () => {
  const day = { date: "2026-11-01", total_protein_g: 100, macro_ranges: { protein_g: [153, 207] } };
  assert.equal(context.nutritionTotalTile("Protein", "protein_g", "g", day, true).className, "nutrition-total nutrition-below-range");
  day.date = "2026-11-02";
  assert.equal(context.nutritionTotalTile("Protein", "protein_g", "g", day, true).className, "nutrition-total");
  day.total_protein_g = 208;
  assert.equal(context.nutritionTotalTile("Protein", "protein_g", "g", day, true).className, "nutrition-total nutrition-above-range");
  day.total_protein_g = null;
  day.known_macro_totals = { protein_g: 300 };
  assert.equal(context.nutritionTotalTile("Protein", "protein_g", "g", day, true).className, "nutrition-total");
});
