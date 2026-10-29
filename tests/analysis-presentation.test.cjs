const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function loadFunctions(file, names, globals = {}) {
  const source = fs.readFileSync(path.join(__dirname, "../public", file), "utf8").replace(/\r\n/g, "\n");
  const chunks = names.map((name) => {
    const start = source.indexOf(`function ${name}(`);
    assert.notEqual(start, -1, `${name} must exist in ${file}`);
    const end = source.indexOf("\n}\n", start);
    assert.notEqual(end, -1, `${name} must have a closing brace at column 0`);
    return source.slice(start, end + 3);
  });
  const context = vm.createContext({ ...globals });
  vm.runInContext(chunks.join("\n"), context);
  return Object.fromEntries(names.map((name) => [name, context[name]]));
}

test("analysis popovers stay inside the viewport on narrow screens and flip above when needed", () => {
  const { analysisPopoverPosition } = loadFunctions("analysis.js", ["analysisPopoverPosition"]);
  const viewport = { width: 360, height: 640 };
  const popover = { width: 340, height: 200 };
  const below = analysisPopoverPosition({ left: 300, top: 80, bottom: 100 }, popover, viewport);
  assert.equal(below.left, 12, "left edge is clamped to the 12px margin");
  assert.equal(below.top, 108, "popover opens below the anchor when it fits");

  const flipped = analysisPopoverPosition({ left: 20, top: 600, bottom: 620 }, popover, viewport);
  assert.equal(flipped.top, 392, "popover opens above the anchor near the bottom edge");

  const short = analysisPopoverPosition({ left: 20, top: 100, bottom: 120 }, { width: 200, height: 280 }, { width: 360, height: 300 });
  assert.ok(short.top >= 12 && short.top + 280 <= 300, "popover that fits neither side is clamped vertically");

  const right = analysisPopoverPosition({ left: 350, top: 80, bottom: 100 }, { width: 200, height: 100 }, viewport);
  assert.equal(right.left, 148, "anchor near the right edge pulls the popover back inside");
});

test("ratio units such as W/bpm keep significant digits and small efficiencies are not rounded to zero", () => {
  const { analysisValue } = loadFunctions("analysis.js", ["analysisRatioUnit", "analysisNumber", "analysisValue"], { AppFormat: require("../public/format.js") });
  assert.equal(analysisValue(0.0234, "(m/s)/bpm"), "0,0234 (m/s)/bpm");
  assert.equal(analysisValue(1.4237, "W/bpm"), "1,42 W/bpm");
  assert.equal(analysisValue(1.5, "W/bpm"), "1,5 W/bpm");
  assert.equal(analysisValue(12.34, "W"), "12,3 W", "other units keep one decimal");
  assert.equal(analysisValue(10.123456789, ""), "10,1");
  assert.equal(analysisValue(null, "W/bpm"), "unbekannt");
});

test("general maximum heart rate preserves the server provider selection", () => {
  const { currentPerformanceValues } = loadFunctions("performance-view.js", ["currentPerformanceValues"]);
  const selected = { value: 187, source_provider: "garmin" };
  const values = currentPerformanceValues({
    running_max_hr_bpm: selected,
    cycling_max_hr_bpm: { value: 200, source_provider: "intervals" },
    max_hr_bpm: selected,
  });
  assert.equal(values.max_hr_bpm, selected);
});

test("race prediction rows exclude body weight and empty states give a reason", () => {
  const { racePredictionRows, racePredictionEmptyReason } = loadFunctions("performance-view.js", ["racePredictionRows", "racePredictionEmptyReason"]);
  const rows = racePredictionRows({
    run_5k_seconds: { value: 1200, source: "Garmin Connect" },
    run_marathon_seconds: { value: null },
    weight_kg: { value: 72.4, source: "Garmin Connect" },
  });
  assert.deepEqual(Array.from(rows, (row) => row.label), ["5 km"]);
  assert.equal(racePredictionRows(undefined).length, 0);

  assert.equal(
    racePredictionEmptyReason({ weight_kg: { value: 72.4 } }),
    "Noch keine Prognosen – dafür fehlen aktuelle Leistungswerte aus Intervals.icu oder Garmin.",
  );
  assert.match(racePredictionEmptyReason({ run_threshold_pace_seconds_per_km: { value: 290 } }), /^Noch keine Prognosen – Laufwerte sind vorhanden/);
});

test("current W/kg uses the preferred provider's newest point and falls back to the newest of all", () => {
  const { isPreferredSource } = loadFunctions("shared.js", ["isPreferredSource"]);
  const { analysisValidPoint } = loadFunctions("analysis.js", ["analysisValidPoint"]);
  const { currentPerformanceValues } = loadFunctions("performance-view.js", ["currentPerformanceValues"], { isPreferredSource, analysisValidPoint });
  const garmin = (points) => ({ source: "Garmin Connect", source_provider: "garmin", points });
  const intervals = (points) => ({ source: "Intervals.icu eFTP", source_provider: "intervals", points });
  const history = (series, preferred) => ({ body: { preferred_providers: preferred, windows: { "12w": { metrics: { cycling_w_per_kg: series } } } } });
  const wPerKg = (series, preferred) => currentPerformanceValues({}, history(series, preferred)).cycling_w_per_kg;

  const older = wPerKg([garmin([{ date: "2026-10-10", value: 3.1 }]), intervals([{ date: "2026-10-14", value: 3.3 }, { date: "2026-10-15", value: 3.4 }])], { cycling_w_per_kg: "garmin" });
  assert.equal(older.value, 3.1, "an older preferred Garmin point wins over newer Intervals points");
  assert.equal(older.source, "Garmin Connect", "the value keeps the Garmin source label");
  assert.equal(older.unit, "W/kg");

  const invalid = wPerKg([garmin([{ date: "2026-10-12", value: null }]), intervals([{ date: "2026-10-14", value: 3.3 }, { date: "2026-10-15", value: 3.4 }])], { cycling_w_per_kg: "garmin" });
  assert.equal(invalid.value, 3.4, "without a valid Garmin point the newest Intervals point is used");
  assert.equal(invalid.source, "Intervals.icu eFTP");
  assert.equal(wPerKg([garmin([]), intervals([{ date: "2026-10-14", value: 3.3 }])], { cycling_w_per_kg: "garmin" }).value, 3.3, "a Garmin series without points falls back too");

  const tie = wPerKg([intervals([{ date: "2026-10-15", value: 3.4 }]), garmin([{ date: "2026-10-15", value: 3.2 }])], { cycling_w_per_kg: "garmin" });
  assert.equal(tie.value, 3.2, "the preferred Garmin point wins a same-date tie");
  const unlabelled = (series) => series.map(({ source_provider, ...item }) => item);
  const byLabel = wPerKg(unlabelled([garmin([{ date: "2026-10-10", value: 3.1 }]), intervals([{ date: "2026-10-15", value: 3.4 }])]), { cycling_w_per_kg: "garmin" });
  assert.equal(byLabel.value, 3.4, "display labels are never compared, so a series without a provider id is not preferred");

  const none = wPerKg([garmin([{ date: "2026-10-10", value: 3.1 }]), intervals([{ date: "2026-10-15", value: 3.4 }])], {});
  assert.equal(none.value, 3.4, "a metric without a preference keeps the newest point");
  assert.equal(wPerKg([], { cycling_w_per_kg: "garmin" }), undefined, "no points at all stay empty");
});

test("analysisHasData is true only when a series holds a valid finite point", () => {
  const { analysisValidPoint, analysisHasData } = loadFunctions("analysis.js", ["analysisValidPoint", "analysisHasData"]);
  const has = (...seriesPoints) => analysisHasData(seriesPoints.map((points) => ({ points })));
  assert.equal(has(), false, "no series at all");
  assert.equal(has([]), false, "a series without points");
  assert.equal(has([{ date: "2026-10-10", value: null }, { date: "2026-10-11", value: "x" }]), false, "only invalid points");
  assert.equal(has([{ date: "2026-10-10", value: null }], [{ date: "2026-10-11", value: 0 }]), true, "partially filled: a zero is a valid measurement");
  assert.equal(has([{ date: "2026-10-10", value: 3.1 }, { date: "2026-10-11", value: 3.4 }]), true, "filled");
  assert.equal(analysisValidPoint({ value: Infinity }), false);
});

test("an analysis chart without data is omitted and its title is listed once as missing", () => {
  const { analysisChart, collectAnalysisChart, analysisMissingDataNote } = loadFunctions(
    "analysis.js",
    ["analysisValidPoint", "analysisHasData", "analysisChart", "collectAnalysisChart", "analysisMissingDataNote"],
    {
      reportNode: (tag, text, className) => ({ tag, text, className }),
    },
  );
  const empty = [{ label: "Garmin", points: [{ date: "2026-10-10", value: null }] }];
  assert.equal(analysisChart("Ruhepuls", empty, "bpm", "2026-10-01", "2026-10-17", ""), null);

  const missing = [];
  assert.equal(collectAnalysisChart(missing, "Ruhepuls", empty, "bpm", "2026-10-01", "2026-10-17", ""), null);
  assert.equal(collectAnalysisChart(missing, "HRV", [], "ms", "2026-10-01", "2026-10-17", ""), null);
  assert.deepEqual(Array.from(missing), ["Ruhepuls", "HRV"]);
  assert.deepEqual({ ...analysisMissingDataNote(missing) }, { tag: "p", text: "Keine Daten: Ruhepuls, HRV", className: "empty" });
  assert.equal(analysisMissingDataNote([]), null, "nothing missing renders no line");
});

test("a filled analysis chart is kept and is not listed as missing", () => {
  const chart = { title: "Gewicht" };
  const { collectAnalysisChart } = loadFunctions("analysis.js", ["collectAnalysisChart"], {
    analysisChart: (title) => (title === "Gewicht" ? chart : null),
  });
  const missing = [];
  assert.equal(collectAnalysisChart(missing, "Gewicht", [{ points: [{ value: 72 }] }]), chart);
  assert.equal(collectAnalysisChart(missing, "Körperfett", []), null);
  assert.deepEqual(Array.from(missing), ["Körperfett"], "only the empty chart is listed");
});

test("body overview uses profile body fat without creating a dated measurement", () => {
  const makeNode = (tag, text) => ({ tag, text, dataset: {}, children: [], append(...items) { this.children.push(...items); }, replaceChildren() { this.children = []; }, querySelectorAll() { return []; } });
  const root = makeNode("div");
  const state = { data: { profile: { body_fat_pct: "18.5" } } };
  const { bodyProfileFat, renderBodyAnalysis } = loadFunctions("analysis.js", ["bodyProfileFat", "bodyOverviewDisplayValue", "renderBodyOverviewRow", "renderBodyAnalysis"], {
    state, document: { getElementById: () => root }, reportNode: makeNode,
    isPreferredSource: () => true, analysisValidPoint: (p) => p.value != null,
    dateLabel: (v) => v, analysisValue: (v, unit) => `${v} ${unit}`,
    analysisPeriodControls: () => makeNode("nav"), bodyHistoryPeriod: "twelveWeeks",
  });
  const body = { windows: {} };
  renderBodyAnalysis(body);
  const rows = root.children[0].children[0].children[1].children;
  assert.equal(rows[1].children[0].children[0].text, "Profil");
  assert.equal(rows[1].children[1].text, "18.5 %");
  assert.equal(bodyProfileFat({ body_fat_pct: "" }), null);
  assert.equal(bodyProfileFat({ body_fat_pct: "18,5" }), 18.5);
  assert.equal(bodyProfileFat({ body_fat_pct: 71 }), null);
});


test("body overview falls back to Garmin when the profile fat is absent", () => {
  const makeNode = (tag, text) => ({ tag, text, dataset: {}, children: [], append(...items) { this.children.push(...items); }, replaceChildren() { this.children = []; }, querySelectorAll() { return []; } });
  const root = makeNode("div");
  const state = { data: { profile: { body_fat_pct: "" } } };
  const { renderBodyAnalysis } = loadFunctions("analysis.js", ["bodyProfileFat", "bodyOverviewDisplayValue", "renderBodyOverviewRow", "renderBodyAnalysis"], {
    state, document: { getElementById: () => root }, reportNode: makeNode,
    isPreferredSource: (item, preferred) => item.source_provider === preferred,
    analysisValidPoint: (point) => point.value != null, dateLabel: (v) => v,
    analysisValue: (v, unit) => `${v} ${unit}`, analysisPeriodControls: () => makeNode("nav"),
    bodyHistoryPeriod: "twelveWeeks", bodyMetricChart: () => null, analysisMissingDataNote: () => makeNode("p"),
  });
  const point = { date: "2026-10-10", value: 16 };
  const body = { preferred_providers: { body_fat_pct: "garmin" }, windows: { "12w": { start: "2026-10-01", end: "2026-10-15", metrics: { body_fat_pct: [{ source_provider: "garmin", points: [point] }] } } } };
  renderBodyAnalysis(body);
  const row = root.children[0].children[0].children[1].children[1];
  assert.equal(row.children[0].children[0].text, "2026-10-10");
  assert.equal(row.children[1].text, "16 %");
  assert.deepEqual(point, { date: "2026-10-10", value: 16 });
});
