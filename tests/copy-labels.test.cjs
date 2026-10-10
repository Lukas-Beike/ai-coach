const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function slice(file, startMarker, endMarker) {
  const source = fs.readFileSync(path.join(__dirname, "../public", file), "utf8");
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start + startMarker.length);
  assert.ok(start >= 0 && end > start, `${file}: ${startMarker} not found`);
  return source.slice(start, end);
}

test("equipment count labels use singular for exactly one and German thousands separators", () => {
  const code = slice("analysis.js", "function analysisCountLabel(", "\nfunction analysisLegendText(");
  const context = vm.createContext({});
  vm.runInContext(code + ";globalThis.countLabel = analysisCountLabel;", context);
  assert.equal(context.countLabel(1, "zugeordnete Einheit", "zugeordnete Einheiten"), "1 zugeordnete Einheit");
  assert.equal(context.countLabel(0, "zugeordnete Einheit", "zugeordnete Einheiten"), "0 zugeordnete Einheiten");
  assert.equal(context.countLabel(2, "Einheit", "Einheiten"), "2 Einheiten");
  assert.equal(context.countLabel(undefined, "Nachweis", "Nachweise"), "0 Nachweise");
  assert.equal(context.countLabel(1234, "Einheit", "Einheiten"), "1.234 Einheiten");
});

test("equipment percentages render with a German decimal comma and no space before %", () => {
  const code = slice("analysis.js", "function analysisPercent(", "\nfunction analysisLegendText(");
  const context = vm.createContext({});
  vm.runInContext(code + ";globalThis.percent = analysisPercent;", context);
  assert.equal(context.percent(42.5), "42,5%");
  assert.equal(context.percent(25), "25%");
  assert.equal(context.percent(125), "125%");
});

test("profile sports are shown in German while stored identifiers stay unchanged", () => {
  const code = slice("views.js", "const PROFILE_SPORT_LABELS", "\nfunction renderProfileSummary(");
  const context = vm.createContext({});
  vm.runInContext(code + ";globalThis.sports = profileSportsLabel;", context);
  assert.equal(context.sports("Cycling,Running,Swimming"), "Radfahren, Laufen, Schwimmen");
  assert.equal(context.sports("Strength"), "Krafttraining");
  assert.equal(context.sports("Rowing"), "Rowing");
  assert.equal(context.sports(""), "");
});
