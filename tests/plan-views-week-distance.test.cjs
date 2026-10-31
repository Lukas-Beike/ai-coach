const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function loadPublicScript(name) {
  const source = fs.readFileSync(path.join(__dirname, "../public", name), "utf8");
  return source.split("\r\n").join("\n");
}

// plan-views.js keeps its helpers private, so load it into a sandbox and expose the week-total helper.
const context = vm.createContext({});
vm.runInContext(loadPublicScript("format.js"), context);
vm.runInContext(`${loadPublicScript("plan-views.js")};globalThis.calendarWeekDistanceLabel = calendarWeekDistanceLabel;`, context);
const { calendarWeekDistanceLabel } = context;

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
  assert.equal(calendarWeekDistanceLabel([{ sport: "swim", distance_m: 1000 }, { sport: "swim" }]), "1,0 km · ohne 1 Aktivität");
  assert.equal(calendarWeekDistanceLabel([{ sport: "row" }, { sport: "hike", distance_m: 0 }]), "– · ohne 2 Aktivitäten");
});
