const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");
const { extractFunctions, loadPublicScript, FakeElement, fakeDocument } = require("./frontend-harness.cjs");

// Golden renders of the chart views (analysis, activity analysis, activity details): fixed synthetic data
// in, the produced element tree serialized to text, compared to the committed fixture.
const FIXTURES = path.join(__dirname, "fixtures", "chart-golden");

function chartDocument() {
  const document = fakeDocument();
  document.getElementById = () => new FakeElement();
  document.body = new FakeElement("body");
  return document;
}

// One line per node: tag (svg: for the SVG namespace), attributes and explicitly set properties with their exact
// names (an explicit "" or false stays visible), data-*, style, listener types with counts, then the children indented.
const INTERNAL = new Set(["tag", "tagName", "children", "attributes", "dataset", "style", "listeners", "classList", "className", "focused", "namespace", "textContent"]);
const SVG_NS = "http://www.w3.org/2000/svg";
function serialize(node, depth = 0) {
  const pad = "  ".repeat(depth);
  if (typeof node === "string") return `${pad}"${node}"`;
  const attributes = {};
  if (node.className) attributes.class = node.className;
  for (const key of node._explicit) {
    if (!INTERNAL.has(key) && node[key] !== undefined) attributes[key] = String(node[key]);
  }
  Object.assign(attributes, node.attributes);
  for (const [key, value] of Object.entries(node.style)) attributes[`style.${key}`] = String(value);
  for (const [key, value] of Object.entries(node.dataset)) attributes[`data-${key.replaceAll(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}`] = String(value);
  for (const [type, count] of Object.entries(node._listenerCounts)) attributes[`on:${type}`] = String(count);
  const rendered = Object.keys(attributes).sort().map((key) => ` ${key}="${attributes[key]}"`).join("");
  const prefix = node.namespace === SVG_NS ? "svg:" : "";
  return [`${pad}<${prefix}${node.tag}${rendered}>`, ...node.children.map((child) => serialize(child, depth + 1))].join("\n");
}

function expectGolden(name, node) {
  const file = path.join(FIXTURES, `${name}.txt`);
  const actual = `${serialize(node)}\n`;
  if (process.env.UPDATE_CHART_GOLDEN) { fs.mkdirSync(FIXTURES, { recursive: true }); fs.writeFileSync(file, actual, "utf8"); }
  assert.equal(actual, fs.readFileSync(file, "utf8").replaceAll("\r\n", "\n"));
}

// One sandbox for the real scripts; the browser globals they read are stubbed with fixed values.
function chartContext(innerWidth) {
  const document = chartDocument();
  const AppFormat = require("../public/format.js");
  const context = vm.createContext({ document, AppFormat, innerWidth, innerHeight: 800, state: { data: { profile: { timezone: "Europe/Berlin" }, configured: {} } }, history: { state: {}, replaceState() {}, pushState() {} }, location: { href: "" }, addEventListener() {}, api: async () => ({}), AppViewRefresh: { create: () => () => {} }, matchMedia: () => ({ matches: false, addEventListener() {} }) });
  extractFunctions("components.js", ["h", "SVG_NS", "svgNode", "table", "createStatusChip", "createEstimateChip", "createLoadingState", "createErrorState", "DATA_LOAD_TIMEOUT_MS"], context);
  extractFunctions("shared.js", ["makeScrollRegionFocusable", "dateLabel", "formatDuration", "formatPace"], context);
  extractFunctions("plan-views.js", ["calendarIntensityLabel"], context);
  return context;
}

test("an analysis chart keeps its rendered tree: pace axis in s/km, a range band, a target line", () => {
  const context = chartContext(1200);
  const { addDateKey } = extractFunctions("views.js", ["dateFromKey", "localDateKey", "addDateKey"], context);
  loadPublicScript("analysis.js", context);
  const pace = [{ label: "Schwellenpace", source: "Garmin Connect", color: 0, points: [
    { date: "2026-10-05", value: 300 }, { date: "2026-10-06", value: null }, { date: "2026-10-07", value: 295 }, { date: "2026-10-08", value: 290 },
  ] }, { label: "Zielpace", line: "dashed", points: [{ date: "2026-10-05", value: 310 }, { date: "2026-10-08", value: 305 }], range: { lower: 285, upper: 315, status: "provisional" } }];
  const sleep = [{ label: "Schlafdauer", unit: "h", bars: true, connected: true, average: true, target: 8, points: [
    { date: "2026-10-05", value: 7.5 }, { date: "2026-10-06", value: 6.8 }, { date: "2026-10-07", value: 8.2 },
  ] }];
  assert.equal(typeof addDateKey, "function");
  expectGolden("analysis-pace", context.analysisChart("Laufpace", pace, "s/km", "2026-10-05", "2026-10-08", "Pace aus Garmin."));
  expectGolden("analysis-target", context.analysisChart("Schlaf", sleep, "h", "2026-10-05", "2026-10-07", "Schlaf aus Garmin.", { estimate: true }));
  const narrow = chartContext(390);
  extractFunctions("views.js", ["dateFromKey", "localDateKey", "addDateKey"], narrow);
  loadPublicScript("analysis.js", narrow);
  expectGolden("analysis-pace-narrow", narrow.analysisChart("Laufpace", pace, "s/km", "2026-10-05", "2026-10-08", "Pace aus Garmin."));
});

const STREAMS = {
  time_s: [0, 60, 120, 180, 240, 300],
  channels: {
    heart_rate_bpm: { values: [120, 128, null, 141, 152, 149] },
    speed_mps: { values: [3, 3.2, 0.1, 3.4, 3.5, 3.3] },
    altitude_m: { values: [100, 102.5, 105, 104, 108, 110] },
  },
};
const ANALYSIS_PAYLOAD = {
  session: { sport: "run", environment: "outdoor" },
  metrics: { avg_hr: { value: 140 }, max_hr: { value: 152 }, avg_speed_mps: { value: 3.2 }, distance_m: { value: 5000 }, moving_duration_s: { value: 1500 } },
  streams: STREAMS,
  zones: { heart_rate: { source: { label: "Garmin" }, buckets: [{ label: "Z1", seconds: 600 }, { label: "Z2", seconds: 900 }] } },
  laps: { laps: [{ moving_duration_s: 300, distance_m: 1000, avg_speed_mps: 3.3, avg_hr: 140 }, { moving_duration_s: 280, distance_m: 1000, avg_speed_mps: 3.5, avg_hr: 150 }] },
  analysis: { form_drift: { status: "ok", flagged: true, label: "Form ließ nach", metrics: { contact_time: { first: 240, last: 252, change_percent: 5, unit: "ms" } } } },
  // Planned steps against the session (#2830): a heart-rate warm-up, a pace rep and an unscored cool-down.
  planned_adherence: {
    status: "ok", score_pct: 88, score_band: "good",
    steps: [
      { step: 1, role: "warmup", metric: "heartrate", low: 110, high: 135, start_s: 0, end_s: 120, target_bpm: [110, 135], time_in_target_pct: 75, band: "fair", actual: 124 },
      { step: 2, role: "work", metric: "speed", low: 3.3, high: 3.6, start_s: 120, end_s: 240, target_pace_s_per_km: [278, 303], time_in_target_pct: 100, band: "good", actual: 290 },
      { step: 3, role: "cooldown", planned_duration_s: 60, start_s: 240, end_s: 300, unscored: "unsupported_target" },
    ],
    zones: { status: "ok", metric: "speed", zones: [{ zone: 1, planned_s: 60, actual_s: 90 }, { zone: 2, planned_s: 0, actual_s: 30 }, { zone: 3, planned_s: 0, actual_s: 0 }, { zone: 4, planned_s: 120, actual_s: 120 }] },
  },
};

test("the activity analysis panel keeps its rendered tree: channel charts with pace, gaps and elevation", async () => {
  const context = chartContext(390);
  loadPublicScript(["activity-details.js", "activity-analysis.js"], context);
  context.api = async () => ANALYSIS_PAYLOAD;
  const panel = new FakeElement("div");
  await context.ActivityAnalysis.loadPanel(panel, { activity_id: "a1", sport: "run" });
  expectGolden("activity-analysis", panel);
});

const DETAIL_PAYLOAD = {
  session: { name: "Testlauf", activity_id: "a1" },
  streams: { time_s: [0, 60, 120, 180, 240], channels: { power_w: { values: [200, 210, null, 230, 225] }, temperature_c: { values: [20, 20, 20, 20, 20] } } },
  laps: { laps: [{ name: "Runde 1", moving_duration_s: 120, avg_power: 205, avg_hr: 140 }, { moving_duration_s: 60 }] },
  strength_sets: {
    source: "garmin_exercise_sets", active_sets: 3, total_reps: 13, volume_kg: 1060,
    exercises: [{ category: "squat", name: "BARBELL_BACK_SQUAT", set_list: [{ reps: 5, weight_kg: 80, rest_s: 120 }, { reps: 5, weight_kg: 82.5, rest_s: null }] }, { category: "plank", name: null, set_list: [{ reps: null, weight_kg: null, duration_s: 60 }] }],
  },
};

test("the activity details dialog keeps its rendered tree: series charts with value tables, laps and strength sets", async () => {
  const context = chartContext(390);
  loadPublicScript("activity-details.js", context);
  await context.ActivityDetails.open({ id: "a1", name: "Testlauf" }, { api: async () => DETAIL_PAYLOAD, showDialog() {} });
  expectGolden("activity-details", context.document.body.children[0]);
});
