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
