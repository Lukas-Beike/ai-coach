const assert = require("node:assert/strict");
const { test } = require("node:test");
const { loadPublicScript, fakeDocument, textOf } = require("./frontend-harness.cjs");

const context = loadPublicScript("plan-views.js", { AppFormat: require("../public/format.js") });

test("competition distances retain unknown, zero and free-form values", () => {
  for (const value of [null, undefined, "", "  ", -1]) assert.equal(context.competitionDistance(value), "Distanz unbekannt");
  assert.equal(context.competitionDistance(0), "0 km");
  assert.equal(context.competitionDistance(42195), "42,2 km");
  assert.equal(context.competitionDistance("Sprintdistanz"), "Sprintdistanz");
});

test("invalid event dates stay undated rather than rolling into another month", () => {
  for (const event_date of [null, "", "2026-02-30", "not-a-date"]) assert.equal(context.competitionDate({ event_date }, "2026-10-24"), false);
  assert.equal(context.competitionDate({ event_date: "2026-10-24" }, "2026-10-24"), true);
});

test("race results show time, distance, pace or power and their source", () => {
  assert.equal(context.competitionResult(null), null);
  assert.equal(
    context.competitionResult({ sport: "run", duration_s: 2400, distance_m: 10000, avg_speed_mps: 10000 / 2400, source: "Garmin Connect" }),
    "40:00 · 10,0 km · 4:00 /km (Garmin Connect)",
  );
  assert.equal(
    context.competitionResult({ sport: "ride", duration_s: 3725, distance_m: 40000, avg_power: 251.4, avg_speed_mps: 10.7 }),
    "1:02:05 · 40,0 km · 251 W",
  );
  assert.equal(
    context.competitionResult({ sport: "ride", duration_s: 3600, distance_m: 36000, avg_speed_mps: 10 }),
    "1:00:00 · 36,0 km · 36 km/h",
  );
  assert.equal(
    context.competitionResult({ sport: "swim", duration_s: 1500, distance_m: 1500, avg_speed_mps: 1 }),
    "25:00 · 1,5 km · 1:40 /100 m",
  );
  assert.equal(context.competitionResult({ sport: "run", source: "Garmin Connect" }), null);
});

const rendered = loadPublicScript("plan-views.js", { AppFormat: require("../public/format.js"), document: fakeDocument() });
const race = { event_date: "2026-11-28", starts_at_local: "2026-11-28T09:00:00" };

test("race plan pacing shows sections with pace or power and its rule", () => {
  const run = rendered.racePlanPacing({ status: "ready", method: "equal_effort", profile_rejected: false, sections: [
    { from_km: 8, to_km: 11, grade_pct: 4, pace_s_per_km: 364, time_s: 1092 },
    { from_km: 15, to_km: 21.1, grade_pct: 0, pace_s_per_km: 294, time_s: 1796 },
  ] }).map(textOf).join("|");
  assert.match(run, /gleiche Anstrengung/);
  assert.match(run, /km 8–11\+4 %6:04\/km18:12/);
  assert.match(run, /km 15–21,10 %4:54\/km29:56/);
  const ride = rendered.racePlanPacing({ status: "ready", method: "power_variation", profile_rejected: true, sections: [
    { from_km: 0, to_km: 40, grade_pct: -2, power_pct: -5, power_w: null },
  ] }).map(textOf).join("|");
  assert.match(ride, /± 5 % Leistung · Streckenprofil nicht erkannt/);
  assert.match(ride, /km 0–40−2 %−5 %/);
  assert.match(rendered.racePlanPacing({ status: "unavailable", reason: "duration" }).map(textOf).join(""), /Zielzeit oder erwartete Dauer fehlt/);
  assert.equal(rendered.racePlanPacing({ status: "unavailable", reason: "sport" }).length, 0);
});

test("race plan carbohydrates name the days, the meal window and the rate", () => {
  const text = rendered.racePlanCarbohydrates({
    source: "Thomas, Erdman und Burke 2016",
    weight: { kg: 70, source: "Garmin" },
    during: { step: "high", low_g: 60, high_g: 120, established_max_g: 90 },
    before: [
      { kind: "loading", days_before: 2, g_per_kg: [10, 12], grams: [700, 840] },
      { kind: "meal", hours_before: [4, 1], g_per_kg: [1, 4], grams: null },
    ],
  }, race).map(textOf).join("|");
  assert.match(text, /Thomas, Erdman und Burke 2016 · Gewicht Garmin/);
  assert.match(text, /Do\.? \+ Fr\.?700–840 g\/Tag/);
  assert.match(text, /Sa\.? 05:00–08:001–4 g\/kg/);
  assert.match(text, /Im Rennen60–120 g\/h · Glukose \+ Fruktose · über 90 g\/h unbelegt/);
  assert.equal(rendered.racePlanMealTime("2026-11-28T00:00:00", [4, 1]), "4–1 h vor dem Start");
  assert.equal(rendered.racePlanDuring({ step: "mouth_rinse" }), "kleine Mengen oder Mund spülen");
  assert.equal(rendered.racePlanDays("kein Datum", 1), "1 Tag davor");
});
