const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { test } = require("node:test");
const source = fs.readFileSync("public/nutrition.js", "utf8");
const start = source.indexOf("function nutritionChartDays(");
const end = source.indexOf("function renderNutritionWeek(", start);
const context = vm.createContext({});
vm.runInContext(source.slice(start, end), context);

test("weekly chart averages observed days independently and preserves empty weeks", () => {
  const days = Array.from({ length: 84 }, (_, index) => ({ date: new Date(Date.UTC(2026, 0, index + 1)).toISOString().slice(0, 10), intake_kcal: null, expenditure_kcal: null }));
  days[0].intake_kcal = 0;
  days[1].intake_kcal = 2000;
  days[1].expenditure_kcal = 2400;
  days[83].expenditure_kcal = 2100;
  const weeks = context.nutritionChartDays(days);
  assert.equal(weeks.length, 12);
  assert.equal(weeks[0].intake_kcal, 1000);
  assert.equal(weeks[0].intake_kcal_days, 2);
  assert.equal(weeks[0].expenditure_kcal_days, 1);
  assert.equal(weeks[1].intake_kcal_days, 0);
  assert.equal(weeks[0].expenditure_kcal, 2400);
  assert.equal(weeks[1].intake_kcal, null);
  assert.equal(weeks[1].expenditure_kcal, null);
  assert.equal(weeks[11].expenditure_kcal, 2100);
  assert.equal(weeks[0].date, days[0].date);
  assert.equal(weeks[11].end_date, days[83].date);
  assert.equal(context.nutritionChartDays(days.slice(0, 14)).length, 14);
});

test("history displays daily balance from paired days alongside the total", () => {
  const nodes = new Map();
  const element = () => ({ children: [], style: {}, append(...children) { this.children.push(...children); }, replaceChildren(...children) { this.children = children; } });
  const document = {
    querySelector(selector) { if (!nodes.has(selector)) nodes.set(selector, element()); return nodes.get(selector); },
    createElement: element,
  };
  const renderStart = source.indexOf("function renderNutritionWeek(");
  const renderEnd = source.indexOf("  const chartDays =", renderStart);
  const valueStart = source.indexOf("function nutritionWeekValue(");
  const valueEnd = source.indexOf("function renderNutritionHistoryPeriod(", valueStart);
  const ctx = vm.createContext({ document, nutritionExpenditureDate: (date) => date, AppFormat: { number: (value) => Math.round(value).toLocaleString("de-DE") } });
  vm.runInContext(source.slice(valueStart, valueEnd) + source.slice(renderStart, renderEnd) + "}\n", ctx);
  for (const [count, balance, paired, expected] of [[14, -4468, 14, "-319 kcal"], [84, -600, 3, "-200 kcal"], [14, 300, 3, "+100 kcal"], [14, 3, 14, "0 kcal"], [14, -5, 14, "0 kcal"], [14, -7, 14, "-1 kcal"], [14, 0, 2, "0 kcal"], [84, null, 0, "Nicht verfügbar"]]) {
    const averages = Object.fromEntries(["intake_kcal", "expenditure_kcal", "carbs_g", "protein_g", "fat_g", "sugar_g", "salt_g"].map((key) => [key, { value: null, days: 0 }]));
    ctx.renderNutritionWeek({ days: Array(count).fill({}), start_date: "start", end_date: "end", balance_kcal: balance, balance_days: paired, averages });
    const tiles = nodes.get("#nutritionWeekTotals").children;
    assert.equal(tiles[1].children[0].textContent, expected);
    assert.equal(tiles[1].children[1].textContent, "Ø Kalorienbilanz pro Tag");
    assert.match(tiles[1].children[2].textContent, new RegExp(`^${paired} von ${count} Tagen`));
    assert.equal(tiles[0].style.gridColumn, undefined);
  }
});
