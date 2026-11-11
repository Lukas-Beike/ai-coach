const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

function nodes() {
  const make = () => ({ hidden: true, textContent: "", dataset: {} });
  return {
    firstThresholdEstimate: make(),
    firstThresholdEstimateText: make(),
    firstThresholdStoredLabel: { textContent: "Gespeichert (% LSHF)" },
  };
}

function render(estimate, profile) {
  const elements = nodes();
  const context = extractFunctions("views.js", ["FIRST_THRESHOLD_QUALITY_LABELS", "firstThresholdEstimateText", "renderFirstThresholdEstimate"], { document: { getElementById: (id) => elements[id] } });
  context.renderFirstThresholdEstimate(estimate, profile);
  return elements;
}

test("the estimate names bpm, percent of the LTHR, sessions and quality and is labelled as an estimate", () => {
  const elements = render({ percent_lthr: 90.5, bpm: 153, sessions: 4, quality: "low" }, {});
  assert.equal(elements.firstThresholdEstimate.hidden, false);
  assert.equal(elements.firstThresholdEstimate.dataset.percent, "90.5");
  assert.equal(elements.firstThresholdEstimateText.textContent, "Schätzung · 153 bpm · 90,5 % LSHF · 4 Einheiten · Qualität niedrig");
});

test("without a current threshold the bpm is left out and one session is singular", () => {
  const elements = render({ percent_lthr: 88, bpm: null, sessions: 1, quality: "good" }, {});
  assert.equal(elements.firstThresholdEstimateText.textContent, "Schätzung · 88 % LSHF · 1 Einheit · Qualität gut");
});

test("no estimate hides the block", () => {
  assert.equal(render(null, {}).firstThresholdEstimate.hidden, true);
});

test("a stored adopted estimate is marked on the stored value", () => {
  const adopted = render(null, { first_threshold_pct: "90", first_threshold_origin: "estimated" });
  assert.equal(adopted.firstThresholdStoredLabel.textContent, "Gespeichert (% LSHF, geschätzt)");
  const measured = render(null, { first_threshold_pct: "90", first_threshold_origin: "measured" });
  assert.equal(measured.firstThresholdStoredLabel.textContent, "Gespeichert (% LSHF)");
});

test("the plan card labels the estimated cap source", () => {
  const plan = fs.readFileSync(path.join(__dirname, "../public/plan-views.js"), "utf8");
  assert.match(plan, /estimated: "geschätzt"/);
});

function adoptContext({ dirty, other = "Ada" }) {
  const elements = { ...nodes(), profileForm: { elements: { first_threshold_pct: { value: "85" } } } };
  const rendered = [];
  const dirtyFlags = [];
  const context = extractFunctions("settings.js", ["applyAdoptedFirstThreshold"], {
    $: (selector) => elements[selector.slice(1)],
    state: {
      profileDirty: dirty,
      profileBaseline: { first_threshold_pct: "85", name: "" },
      data: { profile: { first_threshold_pct: "85", name: "" }, first_threshold_estimate: null },
    },
    profileFieldText: (value) => (typeof value === "string" ? value : ""),
    profileFormValues: (form) => ({ first_threshold_pct: form.elements.first_threshold_pct.value, name: other }),
    determineChangedProfileFields: (values, baseline) => Object.fromEntries(Object.entries(values).filter(([key, value]) => value !== baseline[key])),
    renderFirstThresholdEstimate: (estimate, profile) => rendered.push([estimate, profile.first_threshold_pct]),
    setDirtyIndicator: (id, flag) => dirtyFlags.push([id, flag]),
  });
  return { context, elements, rendered, dirtyFlags };
}

test("an adopted estimate reaches the input and the estimate block while the form holds other edits", () => {
  const { context, elements, rendered, dirtyFlags } = adoptContext({ dirty: true });
  const estimate = { percent_lthr: 90, sessions: 4, quality: "low" };
  context.applyAdoptedFirstThreshold({ profile: { first_threshold_pct: "90", first_threshold_origin: "estimated", name: "" }, first_threshold_estimate: estimate });
  assert.equal(elements.profileForm.elements.first_threshold_pct.value, "90");
  assert.equal(context.state.profileBaseline.first_threshold_pct, "90");
  assert.equal(context.state.data.profile.first_threshold_origin, "estimated");
  assert.deepEqual(rendered, [[estimate, "90"]]);
  // The unsaved name edit stays, so the form is still dirty.
  assert.equal(context.state.profileDirty, true);
  assert.deepEqual(dirtyFlags, [["profileDirtyIndicator", true]]);
});

test("the form is clean again when the adopted value was its only edit", () => {
  const { context, dirtyFlags } = adoptContext({ dirty: true, other: "" });
  context.applyAdoptedFirstThreshold({ profile: { first_threshold_pct: "90", first_threshold_origin: "estimated" }, first_threshold_estimate: null });
  assert.equal(context.state.profileDirty, false);
  assert.deepEqual(dirtyFlags, [["profileDirtyIndicator", false]]);
});
