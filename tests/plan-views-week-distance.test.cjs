const assert = require("node:assert/strict");
const { test } = require("node:test");
const { loadPublicScript } = require("./frontend-harness.cjs");

const { calendarHours, calendarWeekDistance, calendarWeekLoad } = loadPublicScript(["format.js", "plan-views.js"]);
const calendarWeekDistanceLabel = (activities) => {
  const result = calendarWeekDistance(activities);
  return result ? [result.value, result.note].filter(Boolean).join(" · ") : "–";
};

test("week distance counts a distance-bearing sport that is not in the classic list", () => {
  assert.equal(calendarWeekDistanceLabel([{ sport: "swim", distance_m: 1500 }]), "1,5 km");
  assert.equal(calendarWeekDistanceLabel([{ sport: "row", distance_m: 4000 }]), "4,0 km");
});

test("week distance includes any sport with a positive distance", () => {
  assert.equal(calendarWeekDistanceLabel([{ sport: "other", distance_m: 2000 }, { sport: "ride", distance_m: 10000 }]), "12,0 km");
});

test("week distance ignores strength sessions without distance", () => {
  assert.equal(calendarWeekDistanceLabel([{ sport: "strength" }]), "–");
  assert.equal(calendarWeekDistanceLabel([{ sport: "run", distance_m: 5000 }, { sport: "strength", distance_m: null }]), "5,0 km");
});

test("week distance reports distance sports without distance as missing", () => {
  assert.equal(calendarWeekDistanceLabel([{ sport: "swim", distance_m: 1000 }, { sport: "swim" }]), "1,0 km · 1 Aktivität ohne Distanz");
  assert.equal(calendarWeekDistanceLabel([{ sport: "row" }, { sport: "hike", distance_m: 0 }]), "– · 2 Aktivitäten ohne Distanz");
});

test("week load sums known values and names the sessions without one", () => {
  assert.equal(calendarWeekLoad([{ training_load: null }, { training_load: undefined }]), null);
  const partial = calendarWeekLoad([{ training_load: 40 }, { training_load: 35 }, { training_load: null }]);
  assert.equal(partial.value, "75");
  assert.equal(partial.note, "1 Einheit ohne Belastung");
  assert.equal(calendarWeekLoad([{ training_load: 40 }]).note, null);
});

test("week durations always use hours and minutes", () => {
  assert.equal(calendarHours(1800), "0:30 h");
  assert.equal(calendarHours(29100), "8:05 h");
  assert.equal(calendarHours(0), "0:00 h");
});
