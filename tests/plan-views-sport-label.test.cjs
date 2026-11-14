const assert = require("node:assert/strict");
const { test } = require("node:test");
const { loadPublicScript } = require("./frontend-harness.cjs");

const { calendarSportType, activitySportLabel, calendarDisplayName } = loadPublicScript(["performance-view.js", "plan-views.js"]);
const label = (item) => activitySportLabel(calendarSportType(item));

test("completed activities are labelled from the canonical sport and environment", () => {
  assert.equal(label({ sport: "ride", environment: "outdoor" }), "Radfahren");
  assert.equal(label({ sport: "ride", environment: "indoor" }), "Rad indoor");
  assert.equal(label({ sport: "ride", environment: "virtual" }), "Rad indoor");
  assert.equal(label({ sport: "run", environment: "outdoor" }), "Laufen");
  assert.equal(label({ sport: "swim" }), "Schwimmen");
  assert.equal(label({ sport: "strength" }), "Kraft");
  assert.equal(label({ sport: "walk" }), "Andere");
});

test("planned units keep their stored type", () => {
  assert.equal(label({ type: "VirtualRide" }), "Rad indoor");
  assert.equal(label({ type: "Run", sport: "run" }), "Laufen");
});

test("session summaries are labelled without an Intervals type", () => {
  assert.equal(activitySportLabel({ sport: "ride", environment: "virtual" }), "Rad indoor");
  assert.equal(activitySportLabel({ sport: "ride", environment: "outdoor" }), "Radfahren");
  assert.equal(activitySportLabel({ sport: "run" }), "Laufen");
  assert.equal(activitySportLabel({ sport: "yoga" }), "Andere");
});

test("activity names show without the athlete's own place, other names stay intact", () => {
  for (const [stored, shown] of [
    ["Emsdetten - 3 x 10 Min Schwelle", "3 x 10 Min Schwelle"],
    ["Emsdetten – Grundlagenausfahrt", "Grundlagenausfahrt"],
    ["emsdetten — Lockerer Lauf", "Lockerer Lauf"],
    ["Emsdetten - Kontrollierter Schwellenlauf – 3 x 9 Minuten", "Kontrollierter Schwellenlauf – 3 x 9 Minuten"],
    // Another place, no spaced dash or a workout name before the dash: the name stays whole.
    ["Münster - Radfahren", "Münster - Radfahren"],
    ["Emsdetten Laufen", "Emsdetten Laufen"],
    ["Emsdetten-Lauf", "Emsdetten-Lauf"],
    ["Sweet Spot - 3 x 12 min", "Sweet Spot - 3 x 12 min"],
    ["Bergläufe - 6 x 2 min", "Bergläufe - 6 x 2 min"],
    ["Lockerer Lauf – 40 Minuten", "Lockerer Lauf – 40 Minuten"],
    ["Emsdetten -", "Emsdetten -"],
    ["", ""],
  ]) assert.equal(calendarDisplayName(stored, "Emsdetten, Deutschland"), shown, stored);
  assert.equal(calendarDisplayName("Emsdetten - 3 x 10 Min Schwelle", ""), "Emsdetten - 3 x 10 Min Schwelle");
});

test("the calendar sport filter shows a unit by the sport it was done in, else its plan", () => {
  const { calendarSportShown, readCalendarSport } = loadPublicScript(["performance-view.js", "plan-views.js"]);
  const matched = { type: "Run", compliance: { actual_activity: { sport: "ride", environment: "virtual" } } };
  const units = [{ type: "Run" }, { sport: "ride", environment: "virtual", is_completed_activity: true }, { sport: "strength", is_completed_activity: true }, { type: "Swim" }, matched];
  const shown = (sport) => units.filter((unit) => calendarSportShown(unit, sport)).length;
  assert.deepEqual(["all", "run", "ride", "strength"].map(shown), [5, 1, 2, 1]);
  // Without browser storage the calendar shows every sport (#2810).
  assert.equal(readCalendarSport(), "all");
});
