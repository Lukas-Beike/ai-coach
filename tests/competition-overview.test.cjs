const assert = require("node:assert/strict");
const { test } = require("node:test");
const { loadPublicScript } = require("./frontend-harness.cjs");

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
