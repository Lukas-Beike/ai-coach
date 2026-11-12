const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

const NAMES = ["zoneMetricValue", "ZONE_METRIC_LABELS", "ZONE_SPORTS", "POWER_ZONE_NAMES", "zoneConfigurationFor", "zoneLimitsOf", "zoneLimitsText", "zoneLimitValue", "zoneValueText", "zoneRows", "zoneRange", "zoneSourceText", "zoneEditorValues", "FIRST_THRESHOLD_ORIGINS", "firstThresholdSource", "thresholdRows"];

// Garmin's heart-rate zones carry no sport: the server names their key for every sport (#2262).
const GARMIN_HR = { key: "garmin|heart_rate|||2026-11-09", source: "garmin", label: "Garmin", sport: null, metric: "heart_rate", environment: null, threshold: 163, maximum: 186, limits: [130, 145, 155, 166, 186], percent_limits: null };
const LOCAL_POWER = { key: "|power|ride||2026-11-01", source: "local", label: "Lokal", sport: "ride", metric: "power", environment: null, threshold: 285, maximum: null, limits: null, percent_limits: [55, 75, 90, 105, 150], percent_basis: "threshold" };
const EFFECTIVE = [
  { sport: "ride", metric: "heart_rate", environment: null, key: GARMIN_HR.key },
  { sport: "run", metric: "heart_rate", environment: null, key: GARMIN_HR.key },
  { sport: "ride", metric: "power", environment: null, key: LOCAL_POWER.key },
];

// Values built inside the script context have that context's prototypes.
const plain = (value) => JSON.parse(JSON.stringify(value));

function zones(globals = {}) {
  return extractFunctions("settings.js", NAMES, {
    zoneConfigurations: [GARMIN_HR, LOCAL_POWER],
    zoneEffective: EFFECTIVE,
    state: { data: {} },
    formatPace: (seconds) => `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")} min/km`,
    AppFormat: require("../public/format.js"),
    ...globals,
  });
}

test("an all-sports Garmin zone set is shown for every sport and prefills the editor", () => {
  const { zoneConfigurationFor, zoneRows, zoneSourceText, zoneEditorValues } = zones();
  for (const sport of ["ride", "run"]) {
    const shown = zoneConfigurationFor(sport, "heart_rate");
    assert.equal(shown?.key, GARMIN_HR.key, sport);
    assert.equal(zoneSourceText(shown), "Garmin, gilt für alle Sportarten");
    assert.deepEqual(plain(zoneEditorValues(sport, "heart_rate", shown)), { threshold: 163, maximum: 186, limits: "130, 145, 155, 166, 186" });
  }
  assert.deepEqual(plain(zoneRows(GARMIN_HR).map((row) => row.range)), ["bis 130", "131–145", "146–155", "156–166", "ab 167 · max 186"]);
  assert.equal(zoneConfigurationFor("swim", "power"), null, "a kind without zones shows the empty state");
});

test("the cycling FTP prefills the power editor of a sport without power zones", () => {
  const metrics = { cycling_ftp_watts: { value: 265 }, bike_threshold_hr_bpm: { value: 165 }, cycling_max_hr_bpm: { value: 190 }, run_threshold_watts: { value: 300 } };
  const { zoneEditorValues } = zones();
  const read = (key) => (key && metrics[key] ? metrics[key].value : null);
  assert.deepEqual(plain(zoneEditorValues("ride", "power", null, read)), { threshold: 265, maximum: "", limits: "" });
  assert.deepEqual(plain(zoneEditorValues("run", "power", null, read)), { threshold: 300, maximum: "", limits: "" });
  assert.deepEqual(plain(zoneEditorValues("ride", "heart_rate", null, read)), { threshold: 165, maximum: 190, limits: "" });
});

test("power zones show names, watts and the percent of the FTP", () => {
  const { zoneRows } = zones();
  assert.deepEqual(plain(zoneRows(LOCAL_POWER).map((row) => `${row.name}: ${row.range}`)), [
    "Z1 Regeneration: bis 157 W · 55 %",
    "Z2 Grundlage: 158–214 W · 75 %",
    "Z3 Tempo: 215–257 W · 90 %",
    "Z4 Schwelle: 258–299 W · 105 %",
    "Z5 VO2max: ab 300 W",
  ]);
});

test("pace zones read the percent of the threshold speed as paces", () => {
  // The stored limits end with the open top zone's cap.
  const pace = { metric: "pace", percent_limits: [80, 90, 100, 150], threshold: null };
  const { zoneRows } = zones();
  // 4:00 min/km threshold: 80 % of its speed is 5:00, 90 % 4:27, 100 % 4:00.
  assert.deepEqual(plain(zoneRows(pace, 240).map((row) => row.range)), ["langsamer als 5:00 · 80 %", "5:00–4:27 · 90 %", "4:27–4:00 · 100 %", "schneller als 4:00"]);
  // Without a threshold pace (swimming) the limits stay percents.
  assert.deepEqual(plain(zoneRows(pace, null).map((row) => row.range)), ["langsamer als 80 %", "80 %–90 %", "90 %–100 %", "schneller als 100 %"]);
});

test("LT2 comes from the performance values, LT1 and the origin of each value from the thresholds", () => {
  const metrics = { cycling_ftp_watts: { value: 285, source: "Garmin Connect", observed_at: "2026-11-09T08:00:00Z" }, bike_threshold_hr_bpm: { value: 163, source: "Garmin Connect", observed_at: "2026-11-08" } };
  const { thresholdRows, firstThresholdSource } = zones();
  const ride = { hr_bpm: 142, hr_origin: "estimated", watts: 214, power_origin: "zone_2" };
  const rows = thresholdRows("ride", metrics, { first_thresholds: { ride } });
  assert.deepEqual([rows.lt2.main, rows.lt2.hr, rows.lt1.hr, rows.lt1.main], [285, 163, 142, 214]);
  assert.equal(rows.lt1Source, "LT1 aus der Herzfrequenzvariabilität (App), Leistung aus Zone 2");
  assert.equal(rows.lt2Source, "Garmin Connect");
  assert.equal(rows.validFrom, "2026-11-09T08:00:00Z");
  // A fixed share of LT2 is named an estimate once; a measured value names the other origin.
  assert.equal(firstThresholdSource("pace", { hr_origin: "fixed_share", pace_origin: "fixed_share" }), "LT1 Schätzung");
  assert.equal(firstThresholdSource("pace", { hr_origin: "measured", pace_origin: "fixed_share" }), "LT1 gemessen, Pace Schätzung");
  assert.equal(firstThresholdSource("power", { power_origin: "fixed_share" }), "LT1 · Leistung Schätzung");
  const empty = thresholdRows("run", {}, {});
  assert.deepEqual([empty.lt1.main, empty.lt1.hr, empty.lt2.main, empty.lt2.hr, empty.lt1Source], [null, null, null, null, null]);
});
