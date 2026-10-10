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
  assert.equal(calendarWeekDistanceLabel([{ type: "OpenWaterSwim", distance: 1500 }]), "1,5 km");
  assert.equal(calendarWeekDistanceLabel([{ type: "VirtualRow", distance: 4000 }]), "4,0 km");
});

test("week distance includes any activity type with a positive distance", () => {
  assert.equal(calendarWeekDistanceLabel([{ type: "Workout", distance: 2000 }, { type: "Ride", distance: 10000 }]), "12,0 km");
});

test("week distance ignores strength sessions without distance", () => {
  assert.equal(calendarWeekDistanceLabel([{ type: "WeightTraining" }]), "–");
  assert.equal(calendarWeekDistanceLabel([{ type: "Run", distance: 5000 }, { type: "WeightTraining", distance: null }]), "5,0 km");
});

test("week distance reports distance sports without distance as missing", () => {
  assert.equal(calendarWeekDistanceLabel([{ type: "OpenWaterSwim", distance: 1000 }, { type: "OpenWaterSwim" }]), "1,0 km · ohne 1 Aktivität");
  assert.equal(calendarWeekDistanceLabel([{ type: "VirtualRow" }, { type: "Snowshoe", distance: 0 }]), "– · ohne 2 Aktivitäten");
});
