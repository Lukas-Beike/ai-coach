const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions, fakeDocument } = require("./frontend-harness.cjs");

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

test("a nutrition entry without a recorded basis is labelled by its source and leaves the sync state to the card", () => {
  const { nutritionBasisLabel } = extractFunctions("nutrition.js", ["nutritionBasisLabel"]);
  assert.equal(nutritionBasisLabel(undefined, { template: false, syncLabel: " · lokal" }, "Manuelle Angabe"), "Manuelle Angabe");
  assert.equal(nutritionBasisLabel({ kind: "packaging_label" }, {}, "Erfasst"), "Verpackungsangabe");
  assert.equal(nutritionBasisLabel({ kind: "composite" }, {}, "Erfasst"), "");
});

function contextValueNodeFor() {
  return extractFunctions("coach.js", ["CONTEXT_PREVIEW_MAX_DEPTH", "CONTEXT_PREVIEW_MAX_ITEMS", "CONTEXT_HIDDEN_KEYS", "CONTEXT_KEY_LABELS", "contextScalarText", "contextPreNode", "contextTextNode", "contextListNode", "contextObjectNode", "contextValueNode"], {
    document: fakeDocument(),
    formatTime: (value) => value,
  }).contextValueNode;
}

function descendants(node) {
  return node.children.filter((child) => typeof child !== "string").flatMap((child) => [child, ...descendants(child)]);
}

test("the context preview shows readable values and keeps deeply nested provider data as compact text", () => {
  const contextValueNode = contextValueNodeFor();
  const readable = contextValueNode({ unlabelled_key: "ok", flag: true, empty: [], missing: null });
  const text = readable.children.map((node) => node.textContent);
  assert.deepEqual(text, ["unlabelled key", "ok", "flag", "Ja", "empty", "Keine Angaben", "missing", "–"]);
  const nested = descendants(contextValueNode({ a: { b: { c: { d: 1 } } } }));
  assert.deepEqual(nested.filter((node) => node.tag === "pre").map((node) => node.textContent), ['{\n  "d": 1\n}']);
  assert.equal(contextValueNode("Langer Text", "content").tag, "pre");
  const longList = contextValueNode(Array.from({ length: 30 }, (_, index) => index));
  assert.equal(longList.children.length, 26);
  assert.equal(longList.children[25].textContent, "… 5 weitere Einträge");
});
