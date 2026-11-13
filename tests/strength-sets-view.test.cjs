const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const { extractFunctions, loadPublicScript, FakeElement, fakeDocument, textOf } = require("./frontend-harness.cjs");

function text(node) {
  if (typeof node === "string") return node;
  return node.children?.length ? node.children.map(text).join(" ") : String(node.textContent);
}

function loadDetailRenderer(makeScrollRegionFocusable = (region) => region) {
  const document = fakeDocument();
  return extractFunctions("activity-details.js", ["STRENGTH_SOURCES", "strengthExerciseLabel", "strengthNumber", "strengthSeconds", "strengthAmount", "renderStrengthSets"], {
    AppFormat: require("../public/format.js"),
    document,
    makeScrollRegionFocusable,
  }).renderStrengthSets;
}

const STRENGTH = {
  source: "garmin_exercise_sets",
  active_sets: 3,
  total_reps: 13,
  volume_kg: 1060,
  exercises: [
    {
      category: "squat",
      name: "BARBELL_BACK_SQUAT",
      set_list: [
        { reps: 5, weight_kg: 80, rest_s: 120 },
        { reps: 5, weight_kg: 82.5, rest_s: null },
      ],
    },
    { category: "push_up", name: null, set_list: [{ reps: 3, weight_kg: null }] },
    { category: "plank", name: 7, set_list: [{ reps: null, weight_kg: null, duration_s: 60 }] },
  ],
};

test("the detail view lists every executed set with reps, kg and rest", () => {
  const renderStrengthSets = loadDetailRenderer();
  const content = new FakeElement("div");
  renderStrengthSets(STRENGTH, content);
  const all = text(content);
  assert.match(all, /Kraftsätze/);
  assert.match(all, /3 Sätze · 13 Wdh\. · 1\.060 kg Volumen · Garmin-Sätze/);
  assert.match(all, /Kniebeuge – Barbell Back Squat/);
  assert.match(all, /82,5/);
  assert.match(all, /2:00/);
  assert.match(all, /Liegestütz/);
  // A timed set shows its duration; a non-text name falls back to the category.
  assert.match(all, /Unterarmstütz/);
  assert.match(all, /1:00/);
});

test("one exercise header spans all of its set rows", () => {
  const renderStrengthSets = loadDetailRenderer();
  const content = new FakeElement("div");
  renderStrengthSets(STRENGTH, content);
  const table = content.children.find((child) => child.className === "analysis-chart-table").children[0];
  const bodies = table.children.filter((child) => child.tag === "tbody");
  assert.equal(bodies.length, 3, "one row group per exercise");
  const [first, second] = bodies[0].children;
  assert.equal(first.children[0].tag, "th");
  assert.equal(first.children[0].scope, "rowgroup");
  assert.equal(first.children[0].rowSpan, 2);
  assert.equal(second.children[0].tag, "td");
});

test("the set table scrolls in a named region that the keyboard can reach", () => {
  const { makeScrollRegionFocusable } = extractFunctions("shared.js", ["makeScrollRegionFocusable"]);
  const content = new FakeElement("div");
  loadDetailRenderer(makeScrollRegionFocusable)(STRENGTH, content);
  const region = content.children.find((child) => child.className === "analysis-chart-table");
  assert.deepEqual([region.tabIndex, region.attributes.role, region.attributes["aria-label"]], [0, "region", "Kraftsätze"]);
});

test("one set and one omitted exercise use the singular", () => {
  const renderStrengthSets = loadDetailRenderer();
  const content = new FakeElement("div");
  renderStrengthSets({ ...STRENGTH, active_sets: 1, omitted_exercises: 1 }, content);
  const all = text(content);
  assert.match(all, /1 Satz ·/);
  assert.match(all, /1 weitere Übung nicht angezeigt/);
});

test("every canonical exercise category has a German label", () => {
  const vocabulary = fs.readFileSync(path.join(__dirname, "../backend/canonical/vocabulary.py"), "utf8");
  const block = vocabulary.slice(vocabulary.indexOf("class ExerciseCategory"), vocabulary.indexOf("class ZoneBoundarySource"));
  const values = [...block.matchAll(/= "([a-z_]+)"/g)].map((match) => match[1]);
  assert.ok(values.length > 30);
  const { STRENGTH_CATEGORIES } = require("../public/format.js");
  assert.deepEqual(Object.keys(STRENGTH_CATEGORIES).sort(), values.sort());
});

test("a session without sets renders nothing", () => {
  const renderStrengthSets = loadDetailRenderer();
  const content = new FakeElement("div");
  renderStrengthSets(null, content);
  renderStrengthSets({ exercises: [] }, content);
  assert.equal(content.children.length, 0);
});

test("the calendar comparison shows executed sets next to the planned structure", () => {
  const context = loadPublicScript(["performance-view.js", "plan-views.js"], { AppFormat: require("../public/format.js"), document: fakeDocument() });
  const list = context.plannedStrengthRows({
    exercises: [
      { name: "Kniebeuge", category: "squat", status: "matched", planned_sets: 4, planned_reps: 5, planned_kg: 82.5, completed_sets: 2, reps: [5, 5, 3] },
      { name: "Mystery", status: "unknown", planned_sets: 3, planned_reps: 10, planned_kg: null },
      { name: null, category: "deadlift", status: "matched", planned_sets: 1, planned_reps: 5, planned_kg: null, completed_sets: 1, reps: [5] },
    ],
  });
  const [matched, unknown, unnamed] = list.children.map(textOf);
  assert.equal(matched, "Kniebeuge: 2/4 Sätze erreicht · Ist 5/5/3 Wdh. · Plan 4×5 @ 82,5 kg");
  assert.equal(unknown, "Mystery: nicht zugeordnet · Plan 3×10");
  assert.equal(unnamed, "Kreuzheben: 1/1 Sätze erreicht · Ist 5 Wdh. · Plan 1×5");
  assert.equal(context.plannedStrengthRows(null), null);
});
