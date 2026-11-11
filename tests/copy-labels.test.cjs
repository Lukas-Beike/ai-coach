const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

test("equipment count labels use singular for exactly one and German thousands separators", () => {
  const context = extractFunctions("analysis.js", ["analysisCountLabel"]);
  assert.equal(context.analysisCountLabel(1, "zugeordnete Einheit", "zugeordnete Einheiten"), "1 zugeordnete Einheit");
  assert.equal(context.analysisCountLabel(0, "zugeordnete Einheit", "zugeordnete Einheiten"), "0 zugeordnete Einheiten");
  assert.equal(context.analysisCountLabel(2, "Einheit", "Einheiten"), "2 Einheiten");
  assert.equal(context.analysisCountLabel(undefined, "Nachweis", "Nachweise"), "0 Nachweise");
  assert.equal(context.analysisCountLabel(1234, "Einheit", "Einheiten"), "1.234 Einheiten");
});

test("equipment percentages render with a German decimal comma and no space before %", () => {
  const context = extractFunctions("analysis.js", ["analysisPercent"]);
  assert.equal(context.analysisPercent(42.5), "42,5%");
  assert.equal(context.analysisPercent(25), "25%");
  assert.equal(context.analysisPercent(125), "125%");
});

test("profile sports are shown in German while stored identifiers stay unchanged", () => {
  const context = extractFunctions("views.js", ["PROFILE_SPORT_LABELS", "profileSportsLabel"]);
  assert.equal(context.profileSportsLabel("Cycling,Running,Swimming"), "Radfahren, Laufen, Schwimmen");
  assert.equal(context.profileSportsLabel("Strength"), "Krafttraining");
  assert.equal(context.profileSportsLabel("Rowing"), "Rowing");
  assert.equal(context.profileSportsLabel(""), "");
});
