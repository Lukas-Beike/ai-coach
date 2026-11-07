const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function source(name) {
  return fs.readFileSync(path.join(__dirname, "../public", name), "utf8").replace(/\r\n/g, "\n");
}

function element(tag) {
  return {
    tag,
    children: [],
    attributes: {},
    style: {},
    className: "",
    textContent: "",
    append(...items) {
      this.children.push(...items);
    },
    setAttribute(name, value) {
      this.attributes[name] = value;
    },
  };
}

function text(node) {
  return [node.textContent, ...(node.children || []).map(text)].join(" ");
}

function slice(code, start, endMarker) {
  const from = code.indexOf(start);
  assert.notEqual(from, -1, `${start} must exist`);
  return code.slice(from, code.indexOf(endMarker, from));
}

function loadDetailRenderer() {
  const code = source("activity-details.js");
  const context = vm.createContext({
    AppFormat: require("../public/format.js"),
    document: { createElement: (tag) => element(tag) },
    makeScrollRegionFocusable: (region) => region,
  });
  const parts = [
    slice(code, "  function node(", "\n  function chart("),
    slice(code, "  const STRENGTH_SOURCES", "\n  function renderIntervalQuality("),
  ];
  vm.runInContext(`${parts.join("\n")};globalThis.renderStrengthSets = renderStrengthSets;`, context);
  return context.renderStrengthSets;
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
  const content = element("div");
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
  const content = element("div");
  renderStrengthSets(STRENGTH, content);
  const table = content.children.find((child) => child.className === "analysis-chart-table").children[0];
  const body = table.children.find((child) => child.tag === "tbody");
  const [first, second] = body.children;
  assert.equal(first.children[0].tag, "th");
  assert.equal(first.children[0].rowSpan, 2);
  assert.equal(second.children[0].tag, "td");
});

test("one set and one omitted exercise use the singular", () => {
  const renderStrengthSets = loadDetailRenderer();
  const content = element("div");
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
  const content = element("div");
  renderStrengthSets(null, content);
  renderStrengthSets({ exercises: [] }, content);
  assert.equal(content.children.length, 0);
});

test("the calendar comparison shows executed sets next to the planned structure", () => {
  const context = vm.createContext({ AppFormat: require("../public/format.js"), document: { createElement: (tag) => element(tag) } });
  vm.runInContext(source("performance-view.js"), context);
  vm.runInContext(`${source("plan-views.js")};globalThis.plannedStrengthRows = plannedStrengthRows;`, context);
  const list = context.plannedStrengthRows({
    exercises: [
      { name: "Kniebeuge", category: "squat", status: "matched", planned_sets: 4, planned_reps: 5, planned_kg: 82.5, completed_sets: 2, reps: [5, 5, 3] },
      { name: "Mystery", status: "unknown", planned_sets: 3, planned_reps: 10, planned_kg: null },
      { name: null, category: "deadlift", status: "matched", planned_sets: 1, planned_reps: 5, planned_kg: null, completed_sets: 1, reps: [5] },
    ],
  });
  const [matched, unknown, unnamed] = list.children.map((item) => item.textContent);
  assert.equal(matched, "Kniebeuge: 2/4 Sätze erreicht · Ist 5/5/3 Wdh. · Plan 4×5 @ 82,5 kg");
  assert.equal(unknown, "Mystery: nicht zugeordnet · Plan 3×10");
  assert.equal(unnamed, "Kreuzheben: 1/1 Sätze erreicht · Ist 5 Wdh. · Plan 1×5");
  assert.equal(context.plannedStrengthRows(null), null);
});
