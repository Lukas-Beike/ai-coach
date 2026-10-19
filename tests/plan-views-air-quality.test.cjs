const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function loadPublicScript(name) {
  const source = fs.readFileSync(path.join(__dirname, "../public", name), "utf8");
  return source.split("\r\n").join("\n");
}

// plan-views.js keeps its helpers private, so load it into a sandbox and expose the pollen helper.
const context = vm.createContext({});
vm.runInContext(loadPublicScript("format.js"), context);
vm.runInContext(`${loadPublicScript("plan-views.js")};globalThis.plannedPollenLabel = plannedPollenLabel;globalThis.plannedWeatherFlags = plannedWeatherFlags;`, context);
const { plannedPollenLabel } = context;
const plannedWeatherFlags = (weather) => Array.from(context.plannedWeatherFlags(weather));

test("pollen label lists DWD hazard levels by species", () => {
  assert.equal(
    plannedPollenLabel({ source: "DWD", region: "Westfalen", levels: { Birke: "1-2", Gräser: "1" } }),
    "Pollen: Birke 1-2, Gräser 1",
  );
});

test("pollen label reports an empty DWD forecast as no load", () => {
  assert.equal(plannedPollenLabel({ source: "DWD", levels: {} }), "Pollen: keine Belastung");
});

test("pollen label falls back to CAMS concentrations and ignores malformed data", () => {
  assert.equal(plannedPollenLabel({ source: "Open-Meteo/CAMS", concentrations: { Erle: 12 } }), "Pollen: Erle 12");
  assert.equal(plannedPollenLabel(null), "");
  assert.equal(plannedPollenLabel({ source: "DWD", levels: "hoch" }), "");
});

// Day-heading flags appear only for notable values.
test("weather flags stay empty on an ordinary day", () => {
  assert.deepEqual(plannedWeatherFlags({ precipitation_probability_max: 30, air_quality: { european_aqi_max: 42, uv_index_max: 1.3 }, pollen: { source: "DWD", levels: { Birke: "0" } } }), []);
  assert.deepEqual(plannedWeatherFlags(null), []);
});

test("weather flags show rain, UV, air and the strongest pollen when notable", () => {
  const flags = plannedWeatherFlags({
    precipitation_probability_max: 68,
    air_quality: { european_aqi_max: 64, european_aqi_category: "schlecht", uv_index_max: 6.2 },
    pollen: { source: "DWD", levels: { Erle: "1", Birke: "1-2" } },
  });
  assert.deepEqual(flags.map((flag) => flag.text), ["💧 68 %", "☀ UV 6,2", "AQI 64", "🌿 1-2"]);
});

test("CAMS pollen needs a concentration of ten before it is flagged", () => {
  assert.deepEqual(plannedWeatherFlags({ pollen: { source: "Open-Meteo/CAMS", concentrations: { Erle: 9 } } }), []);
  assert.equal(plannedWeatherFlags({ pollen: { source: "Open-Meteo/CAMS", concentrations: { Erle: 12 } } })[0].text, "🌿 12");
});
