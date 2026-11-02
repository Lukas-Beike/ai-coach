const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync("public/nutrition.js", "utf8");
const start = source.indexOf("function nutritionTotalTile(");
const end = source.indexOf("function appendNutritionMacroNote(", start);
const document = { createElement() { return { className: "", classes: [], classList: { add(value) { this.owner.classes.push(value); } }, append() {} }; } };
const create = document.createElement;
document.createElement = () => { const node = create(); node.classList.owner = node; return node; };
const context = vm.createContext({ document, todayIso: () => "2026-11-02", nutritionNumber: String });
vm.runInContext(source.slice(start, end), context);

test("marks complete values outside a range and avoids premature low warnings", () => {
  const day = { date: "2026-11-01", total_protein_g: 100, macro_ranges: { protein_g: [153, 207] } };
  assert.deepEqual(context.nutritionTotalTile("Protein", "protein_g", "g", day, true).classes, ["nutrition-below-range"]);
  day.date = "2026-11-02";
  assert.deepEqual(context.nutritionTotalTile("Protein", "protein_g", "g", day, true).classes, []);
  day.total_protein_g = 208;
  assert.deepEqual(context.nutritionTotalTile("Protein", "protein_g", "g", day, true).classes, ["nutrition-above-range"]);
  day.total_protein_g = null;
  day.known_macro_totals = { protein_g: 300 };
  assert.deepEqual(context.nutritionTotalTile("Protein", "protein_g", "g", day, true).classes, []);
});
